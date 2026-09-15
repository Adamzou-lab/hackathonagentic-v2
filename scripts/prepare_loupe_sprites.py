"""Offline asset preparation, authorized by Adam. Requires Pillow, NumPy, SciPy.

Keeps the source drawings intact in design/loupe/source. Removes only connected
neutral checkerboard regions; never treats the cream face/gloves as background.
Inspect the resulting sprites on both a light and dark background after running.
"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter
from scipy.ndimage import binary_closing, binary_dilation, binary_fill_holes, find_objects, label

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "design/loupe/source"
OUTPUT = ROOT / "design/loupe/assets"


def isolate(image):
    rgba = np.array(image.convert("RGBA"))
    if rgba[:, :, 3].min() == 0:
        return image.convert("RGBA")
    rgb = rgba[:, :, :3].astype(float)
    gray = rgb.mean(axis=2)
    neutral = (np.ptp(rgb, axis=2) < 16) & (gray > 65) & (gray < 245)
    regions, _ = label(neutral)
    background = np.zeros(gray.shape, dtype=bool)
    for index, box in enumerate(find_objects(regions), 1):
        if box is None:
            continue
        region = regions[box] == index
        area = region.sum()
        if area < 500:
            continue
        edge = box[0].start == 0 or box[1].start == 0 or box[0].stop == gray.shape[0] or box[1].stop == gray.shape[1]
        pixels = gray[box][region]
        low, high = np.quantile(pixels, [.1, .9])
        adjacent = region[:, 1:] & region[:, :-1]
        jumps = (np.abs(np.diff(gray[box], axis=1))[adjacent] > 25).mean() if adjacent.any() else 0
        # Enclosed arm/body gaps have the same alternating gray as the outside.
        if edge or (low < 160 and high > 180 and jumps > .06):
            background[box] |= region
    foreground = ~binary_dilation(background, iterations=1)
    components, count = label(foreground)
    sizes = np.bincount(components.ravel())
    sizes[0] = 0
    if count == 0:
        raise ValueError("No character found")
    alpha = Image.fromarray((components == sizes.argmax()).astype("uint8") * 255)
    alpha = alpha.filter(ImageFilter.GaussianBlur(.4))
    result = image.convert("RGBA")
    result.putalpha(alpha)
    return result


def isolate_header(image, pose):
    """Preserve cream interiors using the ink outline of these two drawings.

    The inspected source-coordinate seeds remove enclosed checkerboard gaps,
    without confusing the cream face or gloves with their light background.
    """
    gaps = {
        "loupe-seated-reading": [(815, 720), (524, 840), (615, 915)],
        "loupe-wink": [(715, 665)],
    }
    rgb = np.array(image.convert("RGB")).astype(float)
    gray, chroma = rgb.mean(axis=2), np.ptp(rgb, axis=2)
    ink = binary_closing((gray < 80) | (chroma > 45), iterations=2)
    regions, _ = label(ink)
    sizes = np.bincount(regions.ravel()); sizes[0] = 0
    foreground = binary_fill_holes(regions == sizes.argmax())
    background, _ = label((chroma < 16) & (gray > 175))
    sizes = np.bincount(background.ravel())
    for x, y in gaps[pose]:
        component = background[y, x]
        if component and sizes[component] < gray.size * .03:
            foreground[background == component] = False
    result = image.convert("RGBA")
    alpha = Image.fromarray(foreground.astype("uint8") * 255)
    result.putalpha(alpha.filter(ImageFilter.GaussianBlur(.4)))
    return result


def prepare(source, compact=False, light_checker=False):
    original = Image.open(source)
    sprite = isolate_header(original, source.stem) if light_checker else isolate(original)
    bounds = sprite.getchannel("A").point(lambda p: 255 if p > 128 else 0).getbbox()
    if bounds is None:
        raise ValueError(f"Empty sprite: {source}")
    sprite = sprite.crop(bounds)
    sprite.thumbnail((448, 448), Image.Resampling.LANCZOS)
    size = (sprite.width + 24, sprite.height + 24) if compact else (512, 512)
    canvas = Image.new("RGBA", size)
    position = (12, 12) if compact else ((512 - sprite.width) // 2, 480 - sprite.height)
    canvas.alpha_composite(sprite, position)
    canvas.save(OUTPUT / source.name, optimize=True)
    canvas.save((OUTPUT / source.name).with_suffix(".webp"), quality=86, method=6)
    print(source.stem, size, (OUTPUT / source.name).with_suffix(".webp").stat().st_size, "bytes WebP")


if __name__ == "__main__":
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for pose in ("idle", "paused", "reading", "ready", "search-left", "search-right"):
        prepare(SOURCES / f"loupe-{pose}.png")
    for pose in ("seated-reading", "wink"):
        prepare(SOURCES / f"loupe-{pose}.png", compact=True, light_checker=True)
