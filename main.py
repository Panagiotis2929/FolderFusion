"""FolderFusion - merge subfolders from many folders into one. UI layer (CustomTkinter)."""
from __future__ import annotations

import ctypes
import queue
import sys
import threading
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog
from typing import Callable

import customtkinter as ctk

from branding import APP_NAME, TAGLINE, ensure_assets, render_folder, render_logo, render_symbol
from merge_engine import (
    ConflictMode,
    Issue,
    MergeEngine,
    MergeOptions,
    MergeStats,
    Source,
    list_subfolders,
    open_in_file_manager,
    validate,
)
from settings import Settings
from theme import C, Fonts, Radius, Space

try:  # optional drag & drop support
    from tkinterdnd2 import DND_FILES, TkinterDnD

    class _Base(ctk.CTk, TkinterDnD.DnDWrapper):
        pass

    HAS_DND = True
except Exception:  # noqa: BLE001 - any import problem simply disables drag & drop

    class _Base(ctk.CTk):  # type: ignore[no-redef]
        pass

    HAS_DND = False

VERSION = "1.0.0"
APP_ID = "folderfusion.desktop.app.1"
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
ASSETS_DIR = BASE_DIR / "assets"
MAX_ROWS = 200       # max subfolder checkboxes drawn at once (use the filter for more)
BOTTOM_H = 180       # fixed height of the settings/progress area (prevents layout jumps)
TEXT_HEX = ("#111827", "#ECEEF4")
MUTED_HEX = ("#6B7280", "#8D95AA")


# ----------------------------------------------------------------------------- helpers
def shorten(text: str, limit: int) -> str:
    """Middle-ellipsis for long paths."""
    if len(text) <= limit:
        return text
    head = max(limit // 3, 8)
    return f"{text[:head]}…{text[-(limit - head - 1):]}"


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes} min {secs:02d} s"


def bind_tree(widget: tk.Misc, sequence: str, callback: Callable, skip: tuple = ()) -> None:
    """Bind an event on a widget and all its descendants (except `skip`)."""
    if widget in skip:
        return
    widget.bind(sequence, callback, add="+")
    for child in widget.winfo_children():
        bind_tree(child, sequence, callback, skip)


def pointer_inside(widget: tk.Misc) -> bool:
    try:
        under = widget.winfo_containing(*widget.winfo_pointerxy())
    except (KeyError, tk.TclError):
        return False
    while under is not None:
        if under is widget:
            return True
        under = under.master
    return False


@dataclass(eq=False)
class FolderEntry:
    """A source folder, its subfolders and which of them are selected."""

    path: Path
    subs: list[str]
    selected: set[str] = field(default_factory=set)

    @property
    def name(self) -> str:
        return self.path.name or str(self.path)


# ----------------------------------------------------------------------------- widgets
class Toast(ctk.CTkFrame):
    """Small non-blocking message in the top-right corner."""

    COLORS = {"success": C.TOAST_SUCCESS, "error": C.TOAST_ERROR, "warning": C.TOAST_WARNING, "info": C.ACCENT}

    def __init__(self, master: tk.Misc, fonts: Fonts) -> None:
        super().__init__(master, corner_radius=Radius.CONTROL + 2)
        self._label = ctk.CTkLabel(self, text="", font=fonts.body_bold, text_color=C.ON_ACCENT, anchor="w", justify="left", wraplength=380)
        self._label.pack(padx=18, pady=12)
        self._job: str | None = None

    def show(self, message: str, kind: str = "info", ms: int = 3800) -> None:
        self.configure(fg_color=self.COLORS[kind])
        self._label.configure(text=message)
        self.place(relx=1.0, x=-Space.L, y=Space.L, anchor="ne")
        self.lift()
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(ms, self.hide)

    def hide(self) -> None:
        self.place_forget()
        self._job = None


class FolderCard(ctk.CTkFrame):
    """One selectable source-folder card in the left panel."""

    def __init__(self, master: tk.Misc, app: "App", entry: FolderEntry) -> None:
        super().__init__(master, corner_radius=Radius.CONTROL + 2, fg_color=C.SURFACE_ALT, border_width=1, border_color=C.BORDER)
        self.app, self.entry, self._active = app, entry, False
        self.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self, text="", image=app.img_folder).grid(row=0, column=0, rowspan=3, padx=(14, 10), pady=12)
        ctk.CTkLabel(self, text=entry.name, font=app.fonts.body_bold, anchor="w", text_color=C.TEXT).grid(
            row=0, column=1, sticky="ew", pady=(12, 0)
        )
        ctk.CTkLabel(self, text=shorten(str(entry.path), 44), font=app.fonts.tiny, anchor="w", text_color=C.MUTED).grid(
            row=1, column=1, sticky="ew"
        )
        self.count = ctk.CTkLabel(self, text="", font=app.fonts.tiny, anchor="w", text_color=C.ACCENT)
        self.count.grid(row=2, column=1, sticky="ew", pady=(0, 12))
        self.remove_btn = ctk.CTkButton(
            self, text="", image=app.img_close, width=28, height=28, corner_radius=8,
            fg_color="transparent", hover_color=C.DANGER_SOFT, command=lambda: app.remove_folder(entry),
        )
        self.remove_btn.grid(row=0, column=2, rowspan=2, padx=(0, 10), pady=(10, 0), sticky="ne")

        bind_tree(self, "<Button-1>", lambda _e: app.select_folder(entry), skip=(self.remove_btn,))
        bind_tree(self, "<Enter>", self._on_enter)
        bind_tree(self, "<Leave>", self._on_leave)
        self.refresh()

    def refresh(self) -> None:
        total, sel = len(self.entry.subs), len(self.entry.selected)
        self.count.configure(text=f"{sel} of {total} subfolder{'s' if total != 1 else ''} selected")

    def set_active(self, active: bool) -> None:
        self._active = active
        self.configure(fg_color=C.ACCENT_SOFT if active else C.SURFACE_ALT, border_color=C.ACCENT if active else C.BORDER)

    def _on_enter(self, _e: tk.Event) -> None:
        if not self._active:
            self.configure(fg_color=C.SURFACE_HOVER)

    def _on_leave(self, _e: tk.Event) -> None:
        if not self._active and not pointer_inside(self):
            self.configure(fg_color=C.SURFACE_ALT)


class ResultDialog(ctk.CTkToplevel):
    """Success summary shown after a merge."""

    def __init__(self, app: "App", stats: MergeStats) -> None:
        super().__init__(app, fg_color=C.BG)
        f = app.fonts
        self.title("Merge complete")
        self.resizable(False, False)
        self.transient(app)
        app.apply_icon(self)

        warn = stats.files_failed > 0
        w, h = 480, 400 if warn else 340
        scale = app._get_window_scaling()
        x = int(app.winfo_rootx() + (app.winfo_width() - w * scale) / 2)
        y = int(app.winfo_rooty() + (app.winfo_height() - h * scale) / 2)
        self.geometry(f"{w}x{h}+{max(x, 0)}+{max(y, 0)}")

        card = ctk.CTkFrame(self, corner_radius=Radius.CARD, fg_color=C.SURFACE, border_width=1, border_color=C.BORDER)
        card.pack(fill="both", expand=True, padx=Space.M, pady=Space.M)
        card.grid_columnconfigure((0, 1, 2), weight=1, uniform="stat")

        badge = ctk.CTkFrame(card, width=56, height=56, corner_radius=28, fg_color=C.WARNING if warn else C.SUCCESS)
        badge.grid(row=0, column=0, columnspan=3, pady=(24, 12))
        badge.grid_propagate(False)
        ctk.CTkLabel(badge, text="", image=app.img_check).place(relx=0.5, rely=0.5, anchor="center")

        title = "Finished with some problems" if warn else "Merge complete"
        ctk.CTkLabel(card, text=title, font=f.title, text_color=C.TEXT).grid(row=1, column=0, columnspan=3)
        ctk.CTkLabel(card, text=shorten(str(stats.output), 56), font=f.small, text_color=C.MUTED).grid(
            row=2, column=0, columnspan=3, pady=(2, 16)
        )

        tiles = [
            (f"{stats.files_done:,}", "Files moved" if stats.moved else "Files copied"),
            (f"{stats.folders_merged:,}", "Folders merged"),
            (format_duration(stats.seconds), "Time"),
        ]
        for col, (value, label) in enumerate(tiles):
            tile = ctk.CTkFrame(card, corner_radius=Radius.CONTROL, fg_color=C.SURFACE_ALT)
            tile.grid(row=3, column=col, padx=6, sticky="ew")
            ctk.CTkLabel(tile, text=value, font=f.h2, text_color=C.TEXT).pack(pady=(12, 0))
            ctk.CTkLabel(tile, text=label, font=f.tiny, text_color=C.MUTED).pack(pady=(0, 12))

        row = 4
        extra = []
        if stats.files_skipped:
            extra.append(f"{stats.files_skipped:,} skipped (already existed)")
        if stats.files_failed:
            extra.append(f"{stats.files_failed:,} failed")
        if extra:
            ctk.CTkLabel(card, text="  ·  ".join(extra), font=f.small, text_color=C.WARNING if warn else C.MUTED).grid(
                row=row, column=0, columnspan=3, pady=(12, 0)
            )
            row += 1
        if stats.errors:
            ctk.CTkLabel(
                card, text="\n".join(stats.errors[:3]), font=f.tiny, text_color=C.MUTED, justify="left", wraplength=400
            ).grid(row=row, column=0, columnspan=3, pady=(6, 0))

        buttons = ctk.CTkFrame(card, fg_color="transparent")
        buttons.grid(row=9, column=0, columnspan=3, pady=(20, 24))
        ctk.CTkButton(
            buttons, text="Open folder", width=140, height=40, font=f.button, corner_radius=Radius.CONTROL,
            fg_color=C.ACCENT, hover_color=C.ACCENT_HOVER, text_color=C.ON_ACCENT,
            command=lambda: (open_in_file_manager(stats.output), self.destroy()),
        ).pack(side="left", padx=6)
        ctk.CTkButton(
            buttons, text="Close", width=100, height=40, font=f.button, corner_radius=Radius.CONTROL,
            fg_color=C.SURFACE_ALT, hover_color=C.SURFACE_HOVER, text_color=C.TEXT, command=self.destroy,
        ).pack(side="left", padx=6)
        self.bind("<Escape>", lambda _e: self.destroy())
        self.after(120, self._modal)

    def _modal(self) -> None:
        try:
            self.lift()
            self.focus_force()
            self.grab_set()
        except tk.TclError:
            pass


# ----------------------------------------------------------------------------- application
class App(_Base):
    def __init__(self) -> None:
        super().__init__()
        self.dnd_ok = False
        if HAS_DND:
            try:
                self.TkdndVersion = TkinterDnD._require(self)
                self.dnd_ok = True
            except Exception:  # noqa: BLE001
                self.dnd_ok = False

        self.settings = Settings.load()
        ctk.set_appearance_mode(self.settings.theme)
        self.fonts = Fonts()
        self.title(f"{APP_NAME} - {TAGLINE}")
        self.configure(fg_color=C.BG)
        self.minsize(1040, 660)
        self._center(1200, 780)

        try:
            self.ico_path, self.png_path = ensure_assets(ASSETS_DIR)
        except OSError:
            self.ico_path = self.png_path = ASSETS_DIR / "icon.ico"
        self.apply_icon(self)

        # state
        self.folders: list[FolderEntry] = []
        self.cards: dict[FolderEntry, FolderCard] = {}
        self.active: FolderEntry | None = None
        self._rows: dict[str, ctk.CTkCheckBox] = {}
        self._busy = False
        self._closing = False
        self._cancel = threading.Event()
        self._events: queue.Queue = queue.Queue()
        self._filter_job: str | None = None
        self._last_browse = str(Path.home())

        self._build_images()
        self._build_layout()
        self.toast = Toast(self, self.fonts)
        self._after_folders_changed()
        self._bind_shortcuts()
        if self.dnd_ok:
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self._on_drop)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ setup
    def _center(self, w: int, h: int) -> None:
        scale = self._get_window_scaling()
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = min(w, int(sw / scale) - 40), min(h, int(sh / scale) - 110)
        x, y = int((sw - w * scale) / 2), int((sh - h * scale) / 2) - 20
        self.geometry(f"{w}x{h}+{max(x, 0)}+{max(y, 0)}")

    def apply_icon(self, window: tk.Misc) -> None:
        """Window/taskbar icon (CustomTkinter resets it on Windows, so apply it late)."""
        try:
            if sys.platform == "win32":
                window.after(250, lambda: window.iconbitmap(str(self.ico_path)))
            else:
                self._icon_photo = tk.PhotoImage(file=str(self.png_path))
                window.iconphoto(True, self._icon_photo)
        except tk.TclError:
            pass

    def _bind_shortcuts(self) -> None:
        mods = ["Control"] + (["Command"] if sys.platform == "darwin" else [])
        for mod in mods:
            self.bind(f"<{mod}-o>", lambda _e: self.add_folder_dialog())
            self.bind(f"<{mod}-Return>", lambda _e: self.start_merge())

    def _build_images(self) -> None:
        def pair(fn: Callable[[str], object], size: int, light: str, dark: str) -> ctk.CTkImage:
            return ctk.CTkImage(light_image=fn(light), dark_image=fn(dark), size=(size, size))

        white = "#FFFFFF"
        self.img_logo = ctk.CTkImage(render_logo(192), size=(44, 44))
        self.img_plus = pair(lambda c: render_symbol("plus", 40, c), 20, white, white)
        self.img_merge = pair(lambda c: render_symbol("merge", 48, c), 24, white, white)
        self.img_check = pair(lambda c: render_symbol("check", 64, c), 32, white, white)
        self.img_trash = pair(lambda c: render_symbol("trash", 40, c), 18, TEXT_HEX[0], TEXT_HEX[1])
        self.img_close = pair(lambda c: render_symbol("close", 32, c), 14, MUTED_HEX[0], MUTED_HEX[1])
        self.img_folder = pair(lambda c: render_folder(56, c), 28, "#4F46E5", "#7C83FF")
        self.img_empty = ctk.CTkImage(
            light_image=render_folder(260, "#C9CCF7", "#4F46E5"),
            dark_image=render_folder(260, "#2F3460", "#6366F1"),
            size=(130, 130),
        )

    def _card(self, master: tk.Misc) -> ctk.CTkFrame:
        return ctk.CTkFrame(master, corner_radius=Radius.CARD, fg_color=C.SURFACE, border_width=1, border_color=C.BORDER)

    # ----------------------------------------------------------------- layout
    def _build_layout(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()

        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew", padx=Space.L, pady=(Space.L, Space.M))
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)
        self._build_header(main)
        self._build_body(main)
        self._build_bottom(main)

        ctk.CTkFrame(self, height=1, corner_radius=0, fg_color=C.BORDER).grid(row=1, column=0, columnspan=2, sticky="ew")
        self._build_status_bar()

    def _build_sidebar(self) -> None:
        f = self.fonts
        sb = ctk.CTkFrame(self, width=232, corner_radius=0, fg_color=C.SIDEBAR)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)
        sb.grid_columnconfigure(0, weight=1)
        sb.grid_rowconfigure(4, weight=1)

        brand = ctk.CTkFrame(sb, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=Space.L, pady=(Space.L + 4, Space.L))
        ctk.CTkLabel(brand, text="", image=self.img_logo).grid(row=0, column=0, rowspan=2, padx=(0, 12))
        ctk.CTkLabel(brand, text=APP_NAME, font=f.brand, text_color=C.TEXT, anchor="w").grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(brand, text="Merge Folders... Fast", font=f.tiny, text_color=C.MUTED, anchor="w").grid(row=1, column=1, sticky="w")

        self.add_btn = ctk.CTkButton(
            sb, text="  Add Folder", image=self.img_plus, compound="left", height=44, font=f.button,
            corner_radius=Radius.CONTROL, fg_color=C.ACCENT, hover_color=C.ACCENT_HOVER, text_color=C.ON_ACCENT,
            command=self.add_folder_dialog,
        )
        self.add_btn.grid(row=1, column=0, sticky="ew", padx=Space.L)
        self.clear_btn = ctk.CTkButton(
            sb, text="  Clear All", image=self.img_trash, compound="left", height=40, font=f.body,
            corner_radius=Radius.CONTROL, fg_color="transparent", border_width=1, border_color=C.BORDER,
            hover_color=C.SURFACE_HOVER, text_color=C.TEXT, command=self.clear_all,
        )
        self.clear_btn.grid(row=2, column=0, sticky="ew", padx=Space.L, pady=(Space.S, 0))

        hint = "Drop folders anywhere in the window" if self.dnd_ok else "Pick folders with Add Folder"
        ctk.CTkLabel(sb, text=hint, font=f.tiny, text_color=C.MUTED, wraplength=190, justify="left", anchor="w").grid(
            row=3, column=0, sticky="ew", padx=Space.L, pady=(Space.M, 0)
        )

        bottom = ctk.CTkFrame(sb, fg_color="transparent")
        bottom.grid(row=5, column=0, sticky="ew", padx=Space.L, pady=(0, Space.L))
        self.theme_switch = ctk.CTkSwitch(
            bottom, text="Dark mode", font=f.small, text_color=C.TEXT, command=self._toggle_theme,
            progress_color=C.ACCENT, button_color=C.ON_ACCENT, button_hover_color=C.SURFACE_ALT,
        )
        self.theme_switch.pack(anchor="w")
        if self.settings.theme == "dark":
            self.theme_switch.select()
        ctk.CTkLabel(bottom, text="Ctrl+O add  ·  Ctrl+Enter merge", font=f.tiny, text_color=C.MUTED).pack(anchor="w", pady=(Space.S, 0))

    def _build_header(self, main: ctk.CTkFrame) -> None:
        f = self.fonts
        header = ctk.CTkFrame(main, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", pady=(0, Space.M))
        top = ctk.CTkFrame(header, fg_color="transparent")
        top.pack(anchor="w")
        ctk.CTkLabel(top, text="Merge folders", font=f.title, text_color=C.TEXT, anchor="w").pack(side="left")
        self.summary = ctk.CTkLabel(
            top, text="", width=300, height=28, corner_radius=14, font=f.small,
            fg_color=C.ACCENT_SOFT, text_color=C.ACCENT,
        )
        self.summary.pack(side="left", padx=(Space.M, 0), pady=(4, 0))
        ctk.CTkLabel(
            header, text="Combine subfolders from several folders into one.",
            font=f.body, text_color=C.MUTED, anchor="w",
        ).pack(anchor="w")

    def _build_body(self, main: ctk.CTkFrame) -> None:
        f = self.fonts
        body = ctk.CTkFrame(main, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=5, uniform="panel")
        body.grid_columnconfigure(1, weight=6, uniform="panel")

        # --- left: folders
        left = self._card(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, Space.S))
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)
        head = ctk.CTkFrame(left, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=Space.M, pady=(14, Space.S))
        ctk.CTkLabel(head, text="Folders", font=f.h2, text_color=C.TEXT).pack(side="left")
        self.folder_count = ctk.CTkLabel(head, text="", font=f.small, text_color=C.MUTED)
        self.folder_count.pack(side="left", padx=Space.S)

        self.folder_list = ctk.CTkScrollableFrame(left, fg_color="transparent", corner_radius=0)
        self.folder_list.grid(row=1, column=0, sticky="nsew", padx=(Space.S, 4), pady=(0, Space.S))
        self.empty = ctk.CTkFrame(left, fg_color="transparent")
        self.empty.grid(row=1, column=0, sticky="nsew")
        holder = ctk.CTkFrame(self.empty, fg_color="transparent")
        holder.place(relx=0.5, rely=0.46, anchor="center")
        ctk.CTkLabel(holder, text="", image=self.img_empty).pack()
        ctk.CTkLabel(holder, text="No folders yet", font=f.h2, text_color=C.TEXT).pack(pady=(Space.S, 2))
        hint = "Drop folders here or click Add Folder" if self.dnd_ok else "Click Add Folder to get started"
        ctk.CTkLabel(holder, text=hint, font=f.small, text_color=C.MUTED).pack()
        ctk.CTkButton(
            holder, text="  Add Folder", image=self.img_plus, compound="left", height=40, width=160, font=f.button,
            corner_radius=Radius.CONTROL, fg_color=C.ACCENT, hover_color=C.ACCENT_HOVER, text_color=C.ON_ACCENT,
            command=self.add_folder_dialog,
        ).pack(pady=(Space.M, 0))

        # --- right: subfolders
        right = self._card(body)
        right.grid(row=0, column=1, sticky="nsew", padx=(Space.S, 0))
        right.grid_rowconfigure(2, weight=1)
        right.grid_columnconfigure(0, weight=1)
        head = ctk.CTkFrame(right, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=Space.M, pady=(14, Space.S))
        ctk.CTkLabel(head, text="Subfolders", font=f.h2, text_color=C.TEXT).pack(side="left")
        self.sub_title = ctk.CTkLabel(head, text="", font=f.small, text_color=C.MUTED)
        self.sub_title.pack(side="left", padx=Space.S)

        tools = ctk.CTkFrame(right, fg_color="transparent")
        tools.grid(row=1, column=0, sticky="ew", padx=Space.M, pady=(0, Space.S))
        tools.grid_columnconfigure(0, weight=1)
        self.search = ctk.CTkEntry(
            tools, placeholder_text="Filter subfolders…", height=34, corner_radius=Radius.CONTROL, border_width=1,
            fg_color=C.SURFACE_ALT, border_color=C.BORDER, text_color=C.TEXT, font=f.body,
        )
        self.search.grid(row=0, column=0, sticky="ew")
        self.search.bind("<KeyRelease>", self._on_filter_key)
        for col, (label, value) in enumerate((("Select all", True), ("None", False)), start=1):
            ctk.CTkButton(
                tools, text=label, width=84 if value else 64, height=34, font=f.small, corner_radius=Radius.CONTROL,
                fg_color=C.SURFACE_ALT, hover_color=C.SURFACE_HOVER, text_color=C.TEXT,
                command=lambda v=value: self._set_visible(v),
            ).grid(row=0, column=col, padx=(Space.S, 0))

        self.sub_list = ctk.CTkScrollableFrame(right, fg_color="transparent", corner_radius=0)
        self.sub_list.grid(row=2, column=0, sticky="nsew", padx=(Space.S, 4), pady=(0, Space.S))

    def _build_bottom(self, main: ctk.CTkFrame) -> None:
        f = self.fonts
        self.bottom = ctk.CTkFrame(main, fg_color="transparent", height=BOTTOM_H)
        self.bottom.grid(row=2, column=0, sticky="ew", pady=(Space.M, 0))
        self.bottom.grid_propagate(False)
        self.bottom.grid_columnconfigure(0, weight=1)
        self.bottom.grid_rowconfigure(0, weight=1)

        # --- settings card
        self.settings_card = self._card(self.bottom)
        self.settings_card.grid(row=0, column=0, sticky="nsew")
        sc = self.settings_card
        sc.grid_columnconfigure(0, weight=3)
        sc.grid_columnconfigure(2, weight=2, minsize=190)
        pad = Space.L - 4
        ctk.CTkLabel(sc, text="Output location", font=f.small, text_color=C.MUTED, anchor="w").grid(
            row=0, column=0, columnspan=2, sticky="w", padx=(pad, 0), pady=(Space.M, 4)
        )
        ctk.CTkLabel(sc, text="Merged folder name", font=f.small, text_color=C.MUTED, anchor="w").grid(
            row=0, column=2, sticky="w", padx=(Space.M, 0), pady=(Space.M, 4)
        )

        def entry(**kw) -> ctk.CTkEntry:
            return ctk.CTkEntry(
                sc, height=40, corner_radius=Radius.CONTROL, border_width=1, fg_color=C.SURFACE_ALT,
                border_color=C.BORDER, text_color=C.TEXT, font=f.body, **kw,
            )

        self.out_entry = entry()
        self.out_entry.insert(0, self.settings.output_dir)
        self.out_entry.grid(row=1, column=0, sticky="ew", padx=(pad, Space.S))
        ctk.CTkButton(
            sc, text="Browse", width=84, height=40, font=f.body, corner_radius=Radius.CONTROL,
            fg_color=C.SURFACE_ALT, hover_color=C.SURFACE_HOVER, text_color=C.TEXT, command=self._browse_output,
        ).grid(row=1, column=1)
        self.name_entry = entry(placeholder_text="e.g. Merged_Dataset")
        self.name_entry.grid(row=1, column=2, sticky="ew", padx=(Space.M, 0))
        self.merge_btn = ctk.CTkButton(
            sc, text="  Merge", image=self.img_merge, compound="left", width=150, height=40, font=f.button,
            corner_radius=Radius.CONTROL, fg_color=C.ACCENT, hover_color=C.ACCENT_HOVER, text_color=C.ON_ACCENT,
            command=self.start_merge,
        )
        self.merge_btn.grid(row=1, column=3, padx=(Space.M, pad))
        for e in (self.out_entry, self.name_entry):
            e.bind("<KeyRelease>", lambda _ev: self._clear_issue(), add="+")

        opts = ctk.CTkFrame(sc, fg_color="transparent")
        opts.grid(row=2, column=0, columnspan=4, sticky="w", padx=pad, pady=(Space.M, 0))
        ctk.CTkLabel(opts, text="If a file exists", font=f.small, text_color=C.MUTED).pack(side="left", padx=(0, Space.S))
        self.conflict = ctk.CTkSegmentedButton(
            opts, values=["Rename", "Skip", "Overwrite"], height=32, font=f.small, corner_radius=Radius.CONTROL,
            selected_color=C.ACCENT, selected_hover_color=C.ACCENT_HOVER, unselected_color=C.SURFACE_ALT,
            unselected_hover_color=C.SURFACE_HOVER, text_color=C.TEXT, fg_color=C.SURFACE_ALT,
        )
        self.conflict.set(self.settings.conflict.capitalize())
        self.conflict.pack(side="left")
        switch_kw = dict(font=f.small, text_color=C.TEXT, progress_color=C.ACCENT, button_color=C.ON_ACCENT, button_hover_color=C.SURFACE_ALT)
        self.move_switch = ctk.CTkSwitch(opts, text="Move instead of copy", command=self._on_move_toggle, **switch_kw)
        self.move_switch.pack(side="left", padx=(Space.L, 0))
        self.prefix_switch = ctk.CTkSwitch(opts, text="Prefix files with source name", **switch_kw)
        self.prefix_switch.pack(side="left", padx=(Space.L, 0))
        if self.settings.move:
            self.move_switch.select()
        if self.settings.prefix:
            self.prefix_switch.select()

        self.error = ctk.CTkLabel(sc, text="", height=20, font=f.small, text_color=C.DANGER, anchor="w")
        self.error.grid(row=3, column=0, columnspan=4, sticky="ew", padx=pad, pady=(Space.S, 0))

        # --- progress card (same spot, shown while merging)
        self.progress_card = self._card(self.bottom)
        self.progress_card.grid(row=0, column=0, sticky="nsew")
        pc = self.progress_card
        pc.grid_columnconfigure(0, weight=1)
        self.progress_title = ctk.CTkLabel(pc, text="Merging…", font=f.h2, text_color=C.TEXT, anchor="w")
        self.progress_title.grid(row=0, column=0, sticky="w", padx=pad, pady=(Space.L, 0))
        self.percent = ctk.CTkLabel(pc, text="0%", font=f.h2, text_color=C.ACCENT)
        self.percent.grid(row=0, column=1, sticky="e", padx=pad, pady=(Space.L, 0))
        self.bar = ctk.CTkProgressBar(pc, height=12, corner_radius=6, fg_color=C.SURFACE_ALT, progress_color=C.ACCENT)
        self.bar.set(0)
        self.bar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=pad, pady=(Space.M, Space.S))
        self.progress_file = ctk.CTkLabel(pc, text="", font=f.small, text_color=C.MUTED, anchor="w")
        self.progress_file.grid(row=2, column=0, sticky="ew", padx=pad)
        self.progress_count = ctk.CTkLabel(pc, text="", font=f.small, text_color=C.MUTED)
        self.progress_count.grid(row=2, column=1, sticky="e", padx=pad)
        self.cancel_btn = ctk.CTkButton(
            pc, text="Cancel", width=110, height=38, font=f.button, corner_radius=Radius.CONTROL,
            fg_color=C.DANGER_SOFT, hover_color=C.DANGER, text_color=C.DANGER, command=self._request_cancel,
        )
        self.cancel_btn.grid(row=3, column=1, sticky="e", padx=pad, pady=(Space.M, 0))
        self.progress_card.grid_remove()

    def _build_status_bar(self) -> None:
        bar = ctk.CTkFrame(self, height=30, corner_radius=0, fg_color=C.SIDEBAR)
        bar.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.status = ctk.CTkLabel(bar, text="Ready", font=self.fonts.tiny, text_color=C.MUTED)
        self.status.pack(side="left", padx=Space.M, pady=5)
        ctk.CTkLabel(bar, text=f"{APP_NAME} v{VERSION}", font=self.fonts.tiny, text_color=C.MUTED).pack(side="right", padx=Space.M)

    # ------------------------------------------------------------- folders
    def add_folder_dialog(self) -> None:
        if self._busy:
            return
        chosen = filedialog.askdirectory(title="Choose a folder to merge from", initialdir=self._last_browse)
        if chosen:
            self._last_browse = str(Path(chosen).parent)
            self.add_folder(Path(chosen))

    def add_folder(self, path: Path) -> None:
        path = path.resolve()
        if any(e.path == path for e in self.folders):
            self.toast.show(f"'{path.name}' is already in the list.", "info")
            return
        try:
            subs = list_subfolders(path)
        except OSError as exc:
            self.toast.show(f"Can't read that folder: {exc.strerror or exc}", "error")
            return
        if not subs:
            self.toast.show(f"'{path.name or path}' has no subfolders to merge.", "warning")
            return
        entry = FolderEntry(path, subs, set(subs))
        self.folders.append(entry)
        card = FolderCard(self.folder_list, self, entry)
        card.pack(fill="x", pady=(0, Space.S))
        self.cards[entry] = card
        self.select_folder(entry)
        self._after_folders_changed()
        self.toast.show(f"Added '{entry.name}' ({len(subs)} subfolder{'s' if len(subs) != 1 else ''})", "success", 2400)

    def remove_folder(self, entry: FolderEntry) -> None:
        if self._busy or entry not in self.folders:
            return
        index = self.folders.index(entry)
        self.folders.remove(entry)
        self.cards.pop(entry).destroy()
        if self.active is entry:
            self.select_folder(self.folders[min(index, len(self.folders) - 1)] if self.folders else None)
        self._after_folders_changed()

    def clear_all(self) -> None:
        if self._busy or not self.folders:
            return
        for card in self.cards.values():
            card.destroy()
        self.cards.clear()
        self.folders.clear()
        self.select_folder(None)
        self._after_folders_changed()
        self.toast.show("Cleared all folders.", "info", 1800)

    def select_folder(self, entry: FolderEntry | None) -> None:
        self.active = entry
        for e, card in self.cards.items():
            card.set_active(e is entry)
        if self.search.get():
            self.search.delete(0, "end")
        self.sub_title.configure(text=f"in {entry.name}" if entry else "")
        self._render_subfolders()

    def _after_folders_changed(self) -> None:
        if self.folders:
            self.empty.grid_remove()
            self.folder_list.grid()
        else:
            self.folder_list.grid_remove()
            self.empty.grid()
        n = len(self.folders)
        self.folder_count.configure(text=f"{n} added" if n else "")
        self._refresh_counts()

    def _refresh_counts(self) -> None:
        for card in self.cards.values():
            card.refresh()
        n = len(self.folders)
        if not n:
            self.summary.configure(text="No folders added yet")
            return
        selected = sum(len(e.selected) for e in self.folders)
        total = sum(len(e.subs) for e in self.folders)
        self.summary.configure(text=f"{n} folder{'s' if n != 1 else ''}  ·  {selected} of {total} subfolders selected")

    # ---------------------------------------------------------- subfolders
    def _filtered_names(self) -> list[str]:
        if not self.active:
            return []
        query = self.search.get().strip().casefold()
        return [n for n in self.active.subs if query in n.casefold()]

    def _render_subfolders(self) -> None:
        for widget in self.sub_list.winfo_children():
            widget.destroy()
        self._rows.clear()
        f = self.fonts
        if not self.active:
            self._sub_note("Select a folder on the left\nto choose its subfolders.")
            return
        names = self._filtered_names()
        if not names:
            self._sub_note("No subfolders match your filter.")
            return
        for name in names[:MAX_ROWS]:
            cb = ctk.CTkCheckBox(
                self.sub_list, text=name, font=f.body, text_color=C.TEXT, checkbox_width=22, checkbox_height=22,
                corner_radius=6, border_width=2, fg_color=C.ACCENT, hover_color=C.ACCENT_HOVER,
                border_color=C.MUTED, checkmark_color=C.ON_ACCENT,
            )
            cb.configure(command=lambda n=name, c=cb: self._on_sub_toggle(n, bool(c.get())))
            if name in self.active.selected:
                cb.select()
            cb.pack(fill="x", anchor="w", padx=Space.S, pady=5)
            self._rows[name] = cb
        if len(names) > MAX_ROWS:
            self._sub_note(f"+ {len(names) - MAX_ROWS} more. Use the filter to narrow the list.", pad=Space.S)

    def _sub_note(self, text: str, pad: int = 60) -> None:
        ctk.CTkLabel(self.sub_list, text=text, font=self.fonts.small, text_color=C.MUTED, justify="center").pack(pady=pad)

    def _on_sub_toggle(self, name: str, checked: bool) -> None:
        if not self.active:
            return
        (self.active.selected.add if checked else self.active.selected.discard)(name)
        self._refresh_counts()

    def _set_visible(self, value: bool) -> None:
        """Select/deselect every subfolder matching the current filter."""
        if not self.active or self._busy:
            return
        names = self._filtered_names()
        (self.active.selected.update if value else self.active.selected.difference_update)(names)
        for cb in self._rows.values():
            cb.select() if value else cb.deselect()
        self._refresh_counts()

    def _on_filter_key(self, _event: tk.Event) -> None:
        if self._filter_job:
            self.after_cancel(self._filter_job)
        self._filter_job = self.after(140, self._render_subfolders)

    # ------------------------------------------------------------ settings
    def _browse_output(self) -> None:
        if self._busy:
            return
        chosen = filedialog.askdirectory(title="Where should the merged folder be created?", initialdir=self.out_entry.get() or None)
        if chosen:
            self.out_entry.delete(0, "end")
            self.out_entry.insert(0, chosen)
            self._clear_issue()

    def _toggle_theme(self) -> None:
        self.settings.theme = "dark" if self.theme_switch.get() else "light"
        ctk.set_appearance_mode(self.settings.theme)
        self.settings.save()

    def _on_move_toggle(self) -> None:
        if self.move_switch.get():
            self.toast.show("Move mode: files are removed from the source folders.", "warning", 3200)

    def _show_issue(self, issue: Issue) -> None:
        self._clear_issue()
        self.error.configure(text=issue.message)
        target = {"name": self.name_entry, "output": self.out_entry}.get(issue.field)
        if target is not None:
            target.configure(border_color=C.DANGER)
            target.focus_set()
        self.toast.show(issue.message, "error")

    def _clear_issue(self) -> None:
        if self.error.cget("text"):
            self.error.configure(text="")
        for e in (self.name_entry, self.out_entry):
            e.configure(border_color=C.BORDER)

    # --------------------------------------------------------------- merge
    def _collect(self) -> tuple[list[Source], MergeOptions]:
        sources = [
            Source(e.path, tuple(n for n in e.subs if n in e.selected))
            for e in self.folders
            if e.selected
        ]
        options = MergeOptions(
            output_root=Path(self.out_entry.get().strip()).expanduser(),
            folder_name=self.name_entry.get(),
            conflict=ConflictMode(self.conflict.get().lower()),
            move=bool(self.move_switch.get()),
            prefix_source=bool(self.prefix_switch.get()),
        )
        return sources, options

    def start_merge(self) -> None:
        if self._busy:
            return
        sources, options = self._collect()
        issue = validate(sources, options)
        if issue:
            self._show_issue(issue)
            return
        self._clear_issue()
        self.settings.output_dir = str(options.output_root)
        self.settings.conflict = options.conflict.value
        self.settings.move = options.move
        self.settings.prefix = options.prefix_source
        self.settings.save()

        self._cancel = threading.Event()
        self._events = queue.Queue()
        events = self._events
        engine = MergeEngine(sources, options, lambda d, t, n: events.put(("progress", d, t, n)), self._cancel)

        def work() -> None:
            try:
                events.put(("done", engine.run()))
            except Exception as exc:  # noqa: BLE001 - never let the worker die silently
                events.put(("crash", str(exc)))

        self._set_busy(True)
        threading.Thread(target=work, daemon=True).start()
        self.after(40, self._poll)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        if busy:
            self.progress_title.configure(text="Merging…")
            self.progress_file.configure(text="Scanning folders…")
            self.progress_count.configure(text="")
            self.percent.configure(text="0%")
            self.bar.set(0)
            self.cancel_btn.configure(state="normal", text="Cancel")
            self.settings_card.grid_remove()
            self.progress_card.grid()
            self.status.configure(text="Merging…")
        else:
            self.progress_card.grid_remove()
            self.settings_card.grid()
        state = "disabled" if busy else "normal"
        self.add_btn.configure(state=state)
        self.clear_btn.configure(state=state)

    def _request_cancel(self) -> None:
        self._cancel.set()
        self.cancel_btn.configure(state="disabled", text="Cancelling…")
        self.progress_title.configure(text="Cancelling…")

    def _poll(self) -> None:
        last = result = None
        try:
            while True:
                event = self._events.get_nowait()
                if event[0] == "progress":
                    last = event
                else:
                    result = event
        except queue.Empty:
            pass
        if last:
            _, done, total, name = last
            fraction = done / total if total else 0
            self.bar.set(fraction)
            self.percent.configure(text=f"{int(fraction * 100)}%")
            self.progress_file.configure(text=shorten(name, 70) if name else "Preparing…")
            self.progress_count.configure(text=f"{done:,} of {total:,} files")
        if result:
            self._finish(result)
        else:
            self.after(40, self._poll)

    def _finish(self, result: tuple) -> None:
        self._set_busy(False)
        if self._closing:
            self.destroy()
            return
        if result[0] == "crash":
            self.status.configure(text="Failed")
            self._show_issue(Issue("", f"Unexpected error: {result[1]}"))
            return
        stats: MergeStats = result[1]
        if stats.fatal:
            self.status.configure(text="Failed")
            self._show_issue(Issue("", stats.fatal))
        elif stats.cancelled:
            self.status.configure(text="Cancelled")
            note = f" {stats.files_done:,} files were already moved." if stats.moved and stats.files_done else " Nothing was kept."
            self.toast.show("Merge cancelled." + note, "warning", 4500)
        else:
            self.status.configure(text=f"Done: {stats.files_done:,} files in {format_duration(stats.seconds)}")
            ResultDialog(self, stats)

    # ------------------------------------------------------------ dnd/close
    def _on_drop(self, event: tk.Event) -> None:
        if self._busy:
            return
        added = False
        for raw in self.tk.splitlist(event.data):
            path = Path(raw)
            if path.is_dir():
                self.add_folder(path)
                added = True
        if not added:
            self.toast.show("Drop folders, not files.", "warning")

    def _on_close(self) -> None:
        self.settings.save()
        if self._busy:
            self._closing = True
            self._request_cancel()
        else:
            self.destroy()


def main() -> None:
    if sys.platform == "win32":  # make the taskbar show our icon instead of python.exe's
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except (AttributeError, OSError):
            pass
    ctk.set_default_color_theme("blue")
    App().mainloop()


if __name__ == "__main__":
    main()
