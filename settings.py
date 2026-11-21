"""Tiny JSON settings store (theme, last output folder, merge options)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path


def default_output_dir() -> Path:
    """Desktop if it exists (incl. OneDrive-redirected Desktop), else the home folder."""
    home = Path.home()
    for candidate in (home / "Desktop", home / "OneDrive" / "Desktop"):
        if candidate.is_dir():
            return candidate
    return home


@dataclass
class Settings:
    theme: str = "dark"
    output_dir: str = ""
    conflict: str = "rename"
    move: bool = False
    prefix: bool = True

    @staticmethod
    def path() -> Path:
        return Path.home() / ".folderfusion" / "settings.json"

    @classmethod
    def load(cls) -> "Settings":
        """Load settings; any problem falls back to defaults."""
        settings = cls()
        try:
            data = json.loads(cls.path().read_text(encoding="utf-8"))
            known = {f.name for f in fields(cls)}
            for key, value in data.items():
                if key in known and isinstance(value, type(getattr(settings, key))):
                    setattr(settings, key, value)
        except (OSError, ValueError, AttributeError):
            pass
        if settings.theme not in ("dark", "light"):
            settings.theme = "dark"
        if settings.conflict not in ("rename", "skip", "overwrite"):
            settings.conflict = "rename"
        if not settings.output_dir or not Path(settings.output_dir).is_dir():
            settings.output_dir = str(default_output_dir())
        return settings

    def save(self) -> None:
        try:
            self.path().parent.mkdir(parents=True, exist_ok=True)
            self.path().write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        except OSError:
            pass
