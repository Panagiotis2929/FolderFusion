"""UI-independent merge logic: validation, planning and the (cancellable) copy/move run."""
from __future__ import annotations

import os
import re
import shutil
import sys
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable

ProgressFn = Callable[[int, int, str], None]

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


class ConflictMode(str, Enum):
    RENAME = "rename"
    SKIP = "skip"
    OVERWRITE = "overwrite"


@dataclass(frozen=True)
class Source:
    """A source folder plus the names of the subfolders selected inside it."""

    path: Path
    subfolders: tuple[str, ...]


@dataclass(frozen=True)
class MergeOptions:
    output_root: Path
    folder_name: str
    conflict: ConflictMode = ConflictMode.RENAME
    move: bool = False
    prefix_source: bool = True

    @property
    def out_dir(self) -> Path:
        return self.output_root / self.folder_name


@dataclass(frozen=True)
class Issue:
    """A validation problem. `field` is one of: sources, name, output."""

    field: str
    message: str


@dataclass
class MergeStats:
    output: Path
    files_done: int = 0
    files_skipped: int = 0
    files_failed: int = 0
    folders_merged: int = 0
    seconds: float = 0.0
    cancelled: bool = False
    fatal: str = ""
    moved: bool = False
    errors: list[str] = field(default_factory=list)


def _fs(path: str | os.PathLike) -> str:
    """Absolute path string safe for long paths (adds the \\\\?\\ prefix on Windows)."""
    s = os.path.abspath(os.fspath(path))
    if sys.platform != "win32" or s.startswith("\\\\?\\"):
        return s
    if s.startswith("\\\\"):
        return "\\\\?\\UNC\\" + s[2:]
    return "\\\\?\\" + s


def list_subfolders(path: Path) -> list[str]:
    """Names of the direct subfolders of `path`, sorted case-insensitively."""
    with os.scandir(_fs(path)) as it:
        names = [e.name for e in it if e.is_dir()]
    return sorted(names, key=str.casefold)


def validate_folder_name(name: str) -> str | None:
    """Return an error message if `name` is not a safe folder name, else None."""
    if not name:
        return "Enter a name for the merged folder."
    if _INVALID_CHARS.search(name):
        return 'The name can\'t contain any of < > : " / \\ | ? *'
    if name != name.strip() or name.endswith("."):
        return "The name can't start/end with a space or end with a dot."
    if name.split(".")[0].lower() in _RESERVED:
        return "That name is reserved by the operating system."
    if len(name) > 200:
        return "That name is too long."
    return None


def validate(sources: list[Source], options: MergeOptions) -> Issue | None:
    """Check everything before starting. Returns the first problem found."""
    if not sources:
        return Issue("sources", "Add at least one folder.")
    if not any(s.subfolders for s in sources):
        return Issue("sources", "Select at least one subfolder to merge.")
    for s in sources:
        for sub in s.subfolders:
            if not (s.path / sub).is_dir():
                return Issue("sources", f"'{sub}' no longer exists in {s.path.name or s.path}.")

    root = options.output_root
    if not str(root).strip():
        return Issue("output", "Choose where the merged folder should be created.")
    if not root.is_dir():
        return Issue("output", "The output location doesn't exist.")
    if not os.access(root, os.W_OK):
        return Issue("output", "You don't have permission to write to the output location.")

    msg = validate_folder_name(options.folder_name)
    if msg:
        return Issue("name", msg)

    out = options.out_dir
    if out.exists():
        if not out.is_dir():
            return Issue("name", "A file with this name already exists there.")
        if any(out.iterdir()):
            return Issue("name", f"'{options.folder_name}' already exists there and isn't empty.")

    out_resolved = out.resolve()
    for s in sources:
        for sub in s.subfolders:
            src = (s.path / sub).resolve()
            if out_resolved == src or src in out_resolved.parents:
                return Issue("output", "The output can't be inside a folder you are merging.")
    return None


class MergeEngine:
    """Merges same-named subfolders (case-insensitive) from many sources into one folder."""

    def __init__(
        self,
        sources: list[Source],
        options: MergeOptions,
        on_progress: ProgressFn | None = None,
        cancel: threading.Event | None = None,
    ) -> None:
        self.sources = sources
        self.options = options
        self.on_progress = on_progress or (lambda done, total, name: None)
        self.cancel = cancel or threading.Event()
        self._last_emit = 0.0

    # ------------------------------------------------------------------ run
    def run(self) -> MergeStats:
        """Execute the merge. Never raises; problems are reported in the returned stats."""
        started = time.perf_counter()
        out = self.options.out_dir
        stats = MergeStats(output=out, moved=self.options.move)
        existed = out.exists()
        try:
            os.makedirs(_fs(out), exist_ok=True)
            tasks, stats.folders_merged = self._plan(out)
            total = len(tasks)
            self._emit(0, total, "", force=True)
            for index, (src, dst) in enumerate(tasks):
                if self.cancel.is_set():
                    stats.cancelled = True
                    break
                self._emit(index, total, os.path.basename(src))
                self._transfer(src, dst, stats)
            else:
                self._emit(total, total, "", force=True)
        except PermissionError as exc:
            stats.fatal = f"Permission denied: {exc.filename or exc}"
        except OSError as exc:
            stats.fatal = f"{exc.strerror or exc} ({exc.filename or 'unknown path'})"
        except Exception as exc:  # noqa: BLE001 - last line of defence for the worker thread
            stats.fatal = f"Unexpected error: {exc}"
        finally:
            if stats.cancelled or stats.fatal:
                self._rollback(out, existed)
            stats.seconds = time.perf_counter() - started
        return stats

    # ----------------------------------------------------------------- plan
    def _plan(self, out: Path) -> tuple[list[tuple[str, str]], int]:
        """Group same-named subfolders and list every file to transfer as (src, dst)."""
        groups: dict[str, tuple[str, list[tuple[str, Path]]]] = {}
        for source in self.sources:
            label = source.path.name or "source"
            for sub in source.subfolders:
                _, members = groups.setdefault(sub.casefold(), (sub, []))
                members.append((label, source.path / sub))

        tasks: list[tuple[str, str]] = []
        for display, members in groups.values():
            dest_root = _fs(out / display)
            os.makedirs(dest_root, exist_ok=True)
            for label, src_dir in members:
                src_root = _fs(src_dir)
                for dirpath, dirnames, filenames in os.walk(src_root):
                    dirnames.sort(key=str.casefold)
                    rel = os.path.relpath(dirpath, src_root)
                    dest_dir = dest_root if rel == "." else os.path.join(dest_root, rel)
                    os.makedirs(dest_dir, exist_ok=True)
                    for name in sorted(filenames, key=str.casefold):
                        new_name = f"{label}-{name}" if self.options.prefix_source else name
                        tasks.append((os.path.join(dirpath, name), os.path.join(dest_dir, new_name)))
        return tasks, len(groups)

    # ------------------------------------------------------------- transfer
    def _transfer(self, src: str, dst: str, stats: MergeStats) -> None:
        try:
            if os.path.exists(dst):
                mode = self.options.conflict
                if mode is ConflictMode.SKIP:
                    stats.files_skipped += 1
                    return
                if mode is ConflictMode.RENAME:
                    dst = _unique_path(dst)
            if self.options.move:
                _move(src, dst)
            else:
                shutil.copy2(src, dst)
            stats.files_done += 1
        except OSError as exc:
            stats.files_failed += 1
            if len(stats.errors) < 20:
                stats.errors.append(f"{os.path.basename(src)}: {exc.strerror or exc}")

    def _emit(self, done: int, total: int, name: str, force: bool = False) -> None:
        now = time.perf_counter()
        if force or now - self._last_emit >= 0.04:
            self._last_emit = now
            self.on_progress(done, total, name)

    # ------------------------------------------------------------- rollback
    def _rollback(self, out: Path, existed: bool) -> None:
        """Remove what a failed/cancelled run created. Moved files can't be un-moved."""
        root = _fs(out)
        try:
            if not self.options.move:
                for entry in os.scandir(root):
                    if entry.is_dir(follow_symlinks=False):
                        shutil.rmtree(entry.path, ignore_errors=True)
                    else:
                        os.remove(entry.path)
            else:
                _prune_empty(root)
            if not existed and not os.listdir(root):
                os.rmdir(root)
        except OSError:
            pass


def _unique_path(path: str) -> str:
    """'a.txt' -> 'a (2).txt', 'a (3).txt', ... until the name is free."""
    base, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{base} ({n}){ext}"):
        n += 1
    return f"{base} ({n}){ext}"


def _move(src: str, dst: str) -> None:
    try:
        os.replace(src, dst)
    except OSError:  # e.g. different drives
        shutil.copy2(src, dst)
        os.remove(src)


def _prune_empty(root: str) -> None:
    """Delete empty directories below `root` (bottom-up)."""
    for dirpath, _dirs, _files in os.walk(root, topdown=False):
        if dirpath != root:
            try:
                os.rmdir(dirpath)
            except OSError:
                pass


def open_in_file_manager(path: Path) -> None:
    """Open a folder in Explorer / Finder / the default Linux file manager."""
    import subprocess

    try:
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except OSError:
        pass
