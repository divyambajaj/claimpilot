"""Seeded photo-like degradations: blur, rotation, perspective, crumple noise + shadow, JPEG, crop."""

import io
import random

import numpy as np
from PIL import Image, ImageFilter

TABLE = (196, 190, 178)  # what shows around a rotated/warped receipt


def blur(img: Image.Image, rng: random.Random) -> Image.Image:
    return img.filter(ImageFilter.GaussianBlur(rng.uniform(0.8, 1.6)))


def rotate(img: Image.Image, rng: random.Random) -> Image.Image:
    angle = rng.uniform(3, 12) * rng.choice([-1, 1])
    return img.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=TABLE)


def perspective(img: Image.Image, rng: random.Random) -> Image.Image:
    w, h = img.size
    pad = int(0.06 * max(w, h))
    canvas = Image.new("RGB", (w + 2 * pad, h + 2 * pad), TABLE)
    canvas.paste(img, (pad, pad))
    W, H = canvas.size
    jx = lambda: rng.uniform(0, 0.8 * pad)  # noqa: E731
    jy = lambda: rng.uniform(0, 0.25 * pad)  # noqa: E731 - small vertical skew keeps rows legible
    # destination quad corners (tl, tr, br, bl) jittered inwards; solve the 8 perspective coefficients
    dst = [
        (pad + jx(), pad + jy()),
        (W - pad - jx(), pad + jy()),
        (W - pad - jx(), H - pad - jy()),
        (pad + jx(), H - pad - jy()),
    ]
    src = [(pad, pad), (W - pad, pad), (W - pad, H - pad), (pad, H - pad)]
    a = []
    for (x, y), (u, v) in zip(dst, src, strict=True):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y])
    coeffs = np.linalg.solve(np.array(a, dtype=float), np.array([c for p in src for c in p], dtype=float))
    return canvas.transform(
        (W, H), Image.Transform.PERSPECTIVE, tuple(coeffs), Image.Resampling.BICUBIC, fillcolor=TABLE
    )


def crumple(img: Image.Image, rng: random.Random) -> Image.Image:
    """Low-frequency paper creases + grain + a soft shadow gradient from one side."""
    w, h = img.size
    gen = np.random.default_rng(rng.randrange(2**32))
    small = gen.normal(0, 1, (max(2, h // 60), max(2, w // 60)))
    creases = np.asarray(Image.fromarray(small.astype(np.float32)).resize((w, h), Image.Resampling.BICUBIC))
    grain = gen.normal(0, 4.0, (h, w))
    xs = np.linspace(0, 1, w)[None, :] if rng.random() < 0.5 else np.linspace(0, 1, h)[:, None]
    if rng.random() < 0.5:
        xs = 1 - xs
    shadow = 1 - rng.uniform(0.18, 0.35) * np.clip(1 - xs * 1.6, 0, 1)
    arr = np.asarray(img, dtype=np.float32)
    arr = arr * shadow[..., None] * (1 + 0.035 * creases[..., None]) + grain[..., None]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def jpeg(img: Image.Image, rng: random.Random) -> Image.Image:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=rng.choice([40, 45, 55]))
    return Image.open(io.BytesIO(buf.getvalue())).convert("RGB")


def crop(img: Image.Image, rng: random.Random) -> Image.Image:
    """Re-photograph framing: trim a few percent off the edges (never the middle)."""
    w, h = img.size
    left, top = int(w * rng.uniform(0, 0.04)), int(h * rng.uniform(0, 0.03))
    right, bottom = int(w * rng.uniform(0, 0.04)), int(h * rng.uniform(0, 0.03))
    return img.crop((left, top, w - right, h - bottom))


AUGMENTATIONS = {
    "blur": blur,
    "rotate": rotate,
    "perspective": perspective,
    "crumple": crumple,
    "jpeg": jpeg,
    "crop": crop,
}
ORDER = ("crop", "crumple", "perspective", "rotate", "blur", "jpeg")  # physical order: paper, camera, encoder


def apply(img: Image.Image, names: list[str], rng: random.Random) -> Image.Image:
    for name in sorted(names, key=ORDER.index):
        img = AUGMENTATIONS[name](img, rng)
    return img
