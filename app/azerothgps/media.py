"""The addon's own art from assets/ (`agps media`): the windows' corner logo, pre-scaled, without the
circle, on a plate cut to its outline (CornerLogo<px>.tga; the round portrait's option and art were
removed, 2026-10-01).

A 128-pixel logo shrunk by the graphics card to the corner's 62 UI units looked soft. It's written in
sizes (Media/CornerLogo<px>.tga), each made at that size from the high-resolution logo (Lanczos,
premultiplied alpha), in the top-left corner of the smallest power-of-two canvas that holds it; the addon
shows the size nearest the pixels the logo covers on the player's screen, 1:1 (Core.lua ns.PortraitPx).
Uncompressed 32-bit TGAs, like the addon's other art."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageFilter

# The sizes written (pixels square): the 62-unit portrait at 1080p with a small UI scale to 4K at 1.
# Keep in step with Core.lua's ns.PORTRAIT_PX.
PORTRAIT_PX = (48, 56, 64, 72, 80, 96, 112, 128, 144, 160, 176, 192, 208, 224, 256, 288)
PORTRAIT_BG = (33, 19, 10, 255)  # the title bar's brown, under the logo (the round mask cuts it)
PORTRAIT_SHARE = 0.8  # the logo's longer side, as a share of the portrait's
CORNER_MASTER = 1024  # the corner logo drawn this big first, then scaled to each size
CORNER_PLATE = 18  # ... on a plate of the title bar's brown cut to its outline this many pixels out (at 1024)
CORNER_RIM = (92, 66, 30)  # ... edged in a dark gold line, like the frame's trim (4 pixels more)


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


def corner_master(logo: Path, size: int = CORNER_MASTER) -> Image.Image:
    """The corner logo without the circle (as AzerothGPS-StreetView's game logo): the logo (its visible
    part) the square's width less a margin, on a plate of the title bar's brown following its outline
    (its alpha over 40, CORNER_PLATE pixels out, softened), edged in CORNER_RIM, centered."""
    pad = CORNER_PLATE + 8
    im = Image.open(logo).convert("RGBA")
    im = im.crop(im.getchannel("A").getbbox())
    w = size - 2 * pad
    h = round(im.height * w / im.width)
    art = im.convert("RGBa").resize((w, h), Image.LANCZOS).convert("RGBA")
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(art, (pad, (size - h) // 2))
    alpha = canvas.getchannel("A").point(lambda a: 255 if a > 40 else 0)
    plate = alpha.filter(ImageFilter.MaxFilter(2 * CORNER_PLATE + 1)).filter(ImageFilter.GaussianBlur(2))
    rim = alpha.filter(ImageFilter.MaxFilter(2 * CORNER_PLATE + 9)).filter(ImageFilter.GaussianBlur(2))
    out = Image.new("RGBA", (size, size), CORNER_RIM + (0,))
    out.putalpha(rim)
    brown = Image.new("RGBA", (size, size), PORTRAIT_BG[:3] + (0,))
    brown.putalpha(plate)
    return Image.alpha_composite(Image.alpha_composite(out, brown), canvas)


def scaled(master: Image.Image, px: int) -> Image.Image:
    """`master` px pixels square (Lanczos, premultiplied alpha)."""
    return master.convert("RGBa").resize((px, px), Image.LANCZOS).convert("RGBA")


def on_canvas(img: Image.Image) -> Image.Image:
    """`img` in the top-left corner of the smallest power-of-two canvas that holds it."""
    pot = 1
    while pot < max(img.size):
        pot *= 2
    canvas = Image.new("RGBA", (pot, pot), (0, 0, 0, 0))
    canvas.paste(img, (0, 0))
    return canvas


def make(media: Path, assets: Path) -> list[Path]:
    """Media/CornerLogo<px>.tga for every PORTRAIT_PX, from assets/logo.png. Returns the files written."""
    out = []
    master = corner_master(assets / "logo.png")
    for px in PORTRAIT_PX:
        g = media / f"CornerLogo{px}.tga"
        on_canvas(scaled(master, px)).save(g)
        out.append(g)
    for old in [media / "Logo.tga", *media.glob("Portrait*.tga")]:  # (the one size of before; the round portrait's)
        if old.exists():
            old.unlink()
    return out
