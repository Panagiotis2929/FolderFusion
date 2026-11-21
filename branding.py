"""Programmatic branding: app logo, .ico/.png export and the small UI glyphs (Pillow only)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageOps

APP_NAME = "FolderFusion"
TAGLINE = "Merge Folders... Fast"

_GRAD_FROM = (79, 70, 229)    # indigo
_GRAD_TO = (14, 165, 233)     # sky blue
_SS = 4                       # supersampling factor for glyphs


def _hex(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return tuple(int(color[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _diagonal_gradient(size: int, start: tuple[int, int, int], end: tuple[int, int, int]) -> Image.Image:
    vertical = Image.linear_gradient("L").resize((size, size))
    horizontal = vertical.transpose(Image.Transpose.ROTATE_90)
    diagonal = Image.blend(vertical, horizontal, 0.5)
    diagonal = ImageOps.autocontrast(diagonal)
    return ImageOps.colorize(diagonal, black=start, white=end).convert("RGBA")


def _line(draw: ImageDraw.ImageDraw, pts: list[tuple[float, float]], width: float, fill) -> None:
    """Polyline with round caps and joins."""
    draw.line(pts, fill=fill, width=round(width), joint="curve")
    r = width / 2
    for x, y in (pts[0], pts[-1]):
        draw.ellipse((x - r, y - r, x + r, y + r), fill=fill)


def _draw_merge_symbol(draw: ImageDraw.ImageDraw, s: float, color, ox: float = 0, oy: float = 0, scale: float = 1.0) -> None:
    """Three sources converging into one output arrow (coordinates are 0..1 of `s`)."""

    def p(x: float, y: float) -> tuple[float, float]:
        return ox + (0.5 + (x - 0.5) * scale) * s, oy + (0.5 + (y - 0.5) * scale) * s

    w = 0.062 * s * scale
    for y in (0.29, 0.71):
        _line(draw, [p(0.21, y), p(0.33, y), p(0.50, 0.50)], w, color)
    _line(draw, [p(0.21, 0.50), p(0.50, 0.50)], w, color)
    _line(draw, [p(0.50, 0.50), p(0.68, 0.50)], w, color)
    draw.polygon([p(0.66, 0.36), p(0.66, 0.64), p(0.83, 0.50)], fill=color)
    # slightly round the arrow tip
    r = w / 2.4
    x, y = p(0.815, 0.50)
    draw.ellipse((x - r, y - r, x + r, y + r), fill=color)


def render_logo(size: int = 512) -> Image.Image:
    """Rounded-square gradient tile with the merge symbol."""
    big = 1024
    tile = _diagonal_gradient(big, _GRAD_FROM, _GRAD_TO)

    # soft top-left highlight
    glow = Image.new("L", (big, big), 0)
    ImageDraw.Draw(glow).ellipse((-300, -380, 760, 520), fill=46)
    glow = glow.filter(__import__("PIL.ImageFilter", fromlist=["GaussianBlur"]).GaussianBlur(90))
    tile = Image.composite(Image.new("RGBA", (big, big), (255, 255, 255, 255)), tile, glow)

    draw = ImageDraw.Draw(tile)
    _draw_merge_symbol(draw, big, (255, 255, 255, 255), scale=0.92)
    for y in (0.29, 0.50, 0.71):  # source nodes
        cx, cy = (0.5 + (0.21 - 0.5) * 0.92) * big, (0.5 + (y - 0.5) * 0.92) * big
        r = 0.052 * big
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255, 255))

    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, big - 1, big - 1), radius=int(big * 0.225), fill=255)
    tile.putalpha(ImageChops.multiply(tile.getchannel("A"), mask))
    return tile.resize((size, size), Image.Resampling.LANCZOS)


def render_symbol(kind: str, size: int, color: str) -> Image.Image:
    """Small transparent glyph: plus, trash, merge, check, close, sun, moon."""
    big = size * _SS
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    rgb = _hex(color) + (255,)
    w = big * 0.11
    if kind == "plus":
        _line(d, [(big * 0.5, big * 0.2), (big * 0.5, big * 0.8)], w, rgb)
        _line(d, [(big * 0.2, big * 0.5), (big * 0.8, big * 0.5)], w, rgb)
    elif kind == "close":
        _line(d, [(big * 0.25, big * 0.25), (big * 0.75, big * 0.75)], w, rgb)
        _line(d, [(big * 0.75, big * 0.25), (big * 0.25, big * 0.75)], w, rgb)
    elif kind == "check":
        _line(d, [(big * 0.22, big * 0.52), (big * 0.42, big * 0.72), (big * 0.80, big * 0.30)], w * 1.2, rgb)
    elif kind == "trash":
        _line(d, [(big * 0.2, big * 0.27), (big * 0.8, big * 0.27)], w * 0.9, rgb)
        _line(d, [(big * 0.38, big * 0.27), (big * 0.38, big * 0.17), (big * 0.62, big * 0.17), (big * 0.62, big * 0.27)], w * 0.8, rgb)
        d.rounded_rectangle((big * 0.27, big * 0.32, big * 0.73, big * 0.84), radius=big * 0.07, outline=rgb, width=round(w * 0.9))
        _line(d, [(big * 0.42, big * 0.46), (big * 0.42, big * 0.70)], w * 0.7, rgb)
        _line(d, [(big * 0.58, big * 0.46), (big * 0.58, big * 0.70)], w * 0.7, rgb)
    elif kind == "merge":
        _draw_merge_symbol(d, big, rgb, scale=1.05)
    else:
        raise ValueError(f"unknown symbol: {kind}")
    return img.resize((size, size), Image.Resampling.LANCZOS)


def render_folder(size: int, color: str, plus_color: str | None = None, alpha: int = 255) -> Image.Image:
    """Folder glyph; with `plus_color` it gets a '+' badge (used for the empty state)."""
    big = size * _SS
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    rgba = _hex(color) + (alpha,)
    d.rounded_rectangle((big * 0.07, big * 0.17, big * 0.46, big * 0.40), radius=big * 0.06, fill=rgba)
    d.rounded_rectangle((big * 0.07, big * 0.27, big * 0.93, big * 0.82), radius=big * 0.09, fill=rgba)
    if plus_color:
        cx, cy, r = big * 0.74, big * 0.72, big * 0.21
        d.ellipse((cx - r - big * 0.03, cy - r - big * 0.03, cx + r + big * 0.03, cy + r + big * 0.03), fill=(0, 0, 0, 0))
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=_hex(plus_color) + (255,))
        w = big * 0.045
        _line(d, [(cx, cy - r * 0.5), (cx, cy + r * 0.5)], w, (255, 255, 255, 255))
        _line(d, [(cx - r * 0.5, cy), (cx + r * 0.5, cy)], w, (255, 255, 255, 255))
    return img.resize((size, size), Image.Resampling.LANCZOS)


def ensure_assets(assets_dir: Path) -> tuple[Path, Path]:
    """Create icon.png and a multi-size icon.ico if missing. Returns (ico, png)."""
    assets_dir.mkdir(parents=True, exist_ok=True)
    ico, png = assets_dir / "icon.ico", assets_dir / "icon.png"
    if not (ico.exists() and png.exists()):
        render_logo(512).save(png)
        render_logo(256).save(ico, format="ICO", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    return ico, png


if __name__ == "__main__":
    folder = Path(__file__).parent / "assets"
    for name in ("icon.ico", "icon.png"):
        (folder / name).unlink(missing_ok=True)
    print("Created:", *ensure_assets(folder))
