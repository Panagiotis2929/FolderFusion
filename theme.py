"""Design tokens: every color, spacing value, radius and font lives here.

Colors are (light, dark) pairs, which CustomTkinter switches automatically
when the appearance mode changes.
"""
from __future__ import annotations

import sys

import customtkinter as ctk

Color = tuple[str, str]


class C:
    """Color palette: neutral surfaces + a single indigo accent."""

    BG: Color = ("#F3F5F9", "#0E1016")
    SIDEBAR: Color = ("#FFFFFF", "#12151D")
    SURFACE: Color = ("#FFFFFF", "#171A23")
    SURFACE_ALT: Color = ("#F1F3F8", "#202431")
    SURFACE_HOVER: Color = ("#E6EAF3", "#2A2F3F")
    BORDER: Color = ("#E1E5EE", "#2A2F3E")
    TEXT: Color = ("#111827", "#ECEEF4")
    MUTED: Color = ("#6B7280", "#8D95AA")
    ACCENT: Color = ("#4F46E5", "#6366F1")
    ACCENT_HOVER: Color = ("#4338CA", "#7C83FF")
    ACCENT_PRESSED: Color = ("#3730A3", "#4F46E5")
    ACCENT_SOFT: Color = ("#E8E9FD", "#23274D")
    ON_ACCENT: Color = ("#FFFFFF", "#FFFFFF")
    SUCCESS: Color = ("#16A34A", "#22C55E")
    WARNING: Color = ("#D97706", "#F59E0B")
    DANGER: Color = ("#DC2626", "#F87171")
    DANGER_SOFT: Color = ("#FDE8E8", "#3B1F25")
    TOAST_SUCCESS: Color = ("#15803D", "#15803D")
    TOAST_ERROR: Color = ("#B91C1C", "#B91C1C")
    TOAST_WARNING: Color = ("#B45309", "#B45309")


class Space:
    """Spacing scale (8px grid)."""

    XS, S, M, L, XL = 4, 8, 16, 24, 32


class Radius:
    CARD = 16
    CONTROL = 10


def font_family() -> str:
    """Pick a good system UI font for the current platform."""
    if sys.platform == "win32":
        return "Segoe UI"
    if sys.platform == "darwin":
        return "Helvetica Neue"
    return "DejaVu Sans"


class Fonts:
    """CTkFont set. Create only after the Tk root exists."""

    def __init__(self) -> None:
        fam = font_family()
        self.brand = ctk.CTkFont(fam, 19, "bold")
        self.title = ctk.CTkFont(fam, 24, "bold")
        self.h2 = ctk.CTkFont(fam, 15, "bold")
        self.body = ctk.CTkFont(fam, 13)
        self.body_bold = ctk.CTkFont(fam, 13, "bold")
        self.small = ctk.CTkFont(fam, 12)
        self.tiny = ctk.CTkFont(fam, 11)
        self.button = ctk.CTkFont(fam, 13, "bold")
