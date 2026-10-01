"""The addon's own art from assets/ (`agps media`): the logo in the windows' round portrait, pre-scaled.

A 128-pixel logo shrunk by the graphics card to the portrait's 62 UI units looked soft. The portrait is
written in sizes (Media/Portrait<px>.tga), each made at that size from the high-resolution logo
(Lanczos, premultiplied alpha), in the top-left corner of the smallest power-of-two canvas that holds it; the
addon shows the size nearest the pixels the portrait covers on the player's screen, 1:1
(Core.lua ns.FitPortrait). Uncompressed 32-bit TGAs, like the addon's other art."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

# The sizes written (pixels square): the 62-unit portrait at 1080p with a small UI scale to 4K at 1.
# Keep in step with Core.lua's ns.PORTRAIT_PX.
PORTRAIT_PX = (48, 56, 64, 72, 80, 96, 112, 128, 144, 160, 176, 192, 208, 224, 256, 288)
PORTRAIT_BG = (33, 19, 10, 255)  # the title bar's brown, under the logo (the round mask cuts it)
PORTRAIT_SHARE = 0.8  # the logo's longer side, as a share of the portrait's


def portrait(logo: Path, px: int) -> Image.Image:
    """The portrait's picture, px square: the logo (its visible part) at PORTRAIT_SHARE of the square,
    its longer side, centered on the solid brown. (At 128 pixels, this is the Logo.tga of before.)"""
    src = Image.open(logo).convert("RGBA")
    crop = src.crop(src.getchannel("A").getbbox())
    w0, h0 = crop.size
    s = px * PORTRAIT_SHARE / max(w0, h0)
    w, h = max(1, round(w0 * s)), max(1, round(h0 * s))
    small = crop.convert("RGBa").resize((w, h), Image.LANCZOS).convert("RGBA")
    out = Image.new("RGBA", (px, px), PORTRAIT_BG)
    out.alpha_composite(small, ((px - w) // 2, (px - h) // 2))
    return out


def on_canvas(img: Image.Image) -> Image.Image:
    """`img` in the top-left corner of the smallest power-of-two canvas that holds it."""
    pot = 1
    while pot < max(img.size):
        pot *= 2
    canvas = Image.new("RGBA", (pot, pot), (0, 0, 0, 0))
    canvas.paste(img, (0, 0))
    return canvas


def make(media: Path, assets: Path) -> list[Path]:
    """Media/Portrait<px>.tga for every PORTRAIT_PX, from assets/logo.png. Returns the files written."""
    out = []
    for px in PORTRAIT_PX:
        f = media / f"Portrait{px}.tga"
        on_canvas(portrait(assets / "logo.png", px)).save(f)
        out.append(f)
    old = media / "Logo.tga"  # (the one size of before)
    if old.exists():
        old.unlink()
    return out
