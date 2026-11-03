"""Builds packaging/bladesmith.ico: the Sanguine blade render for 64 px and up, the same blade drawn as plain
shapes for 48 px and below, where a 2048 px render shrinks to a one-pixel line.
usage: python packaging/make_icon.py  (needs the weapon renders the app caches on its first start)"""
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bladesmith import config  # noqa: E402

S = 512
BG, GLOW = (20, 18, 21, 255), (118, 18, 30, 255)


def glow_tile(w, radius):
    im = Image.new("RGBA", (w, w), (0, 0, 0, 0))
    mask = Image.new("L", (w, w), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, w - 1), radius, fill=255)
    t = Image.new("RGBA", (w, w), BG)
    g = Image.new("L", (w, w), 0)
    ImageDraw.Draw(g).ellipse((w * .17, w * .17, w * .83, w * .88), fill=170)
    t.paste(Image.new("RGBA", (w, w), GLOW), (0, 0), g.filter(ImageFilter.GaussianBlur(w * .14)))
    im.paste(t, (0, 0), mask)
    return im


def render_icon(render: Path):
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    im.alpha_composite(glow_tile(S - 32, 96), (16, 16))
    b = Image.open(render).convert("RGBA")
    b = b.crop(b.getchannel("A").getbbox())
    b = b.resize((int(b.width * 440 / b.height), 440), Image.LANCZOS).rotate(-28, resample=Image.BICUBIC, expand=True)
    x, y = (S - b.width) // 2, (S - b.height) // 2
    shadow = Image.new("RGBA", b.size, (0, 0, 0, 0))
    shadow.putalpha(b.getchannel("A").point(lambda v: int(v * .65)))
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    layer.alpha_composite(shadow, (x + 10, y + 14))
    im.alpha_composite(layer.filter(ImageFilter.GaussianBlur(10)))
    im.alpha_composite(b, (x, y))
    return im


def vector_icon(n):
    k = 8
    w = n * k
    im = glow_tile(w, max(2, int(w * .19)))
    d = ImageDraw.Draw(im)
    tip, base = (w * .17, w * .83), (w * .66, w * .34)
    ang = math.atan2(base[1] - tip[1], base[0] - tip[0])
    nx, ny = -math.sin(ang) * w * .085, math.cos(ang) * w * .085
    d.polygon([tip, (base[0] + nx, base[1] + ny), (base[0] - nx, base[1] - ny)], fill=(196, 40, 52, 255))
    d.polygon([(tip[0] + w * .02, tip[1] - w * .02), (base[0] - nx * .2, base[1] - ny * .2), (base[0] - nx, base[1] - ny)],
              fill=(232, 86, 92, 255))  # lit edge
    ca, sa = math.cos(ang + math.pi / 2) * w * .17, math.sin(ang + math.pi / 2) * w * .17
    d.line([(base[0] - ca, base[1] - sa), (base[0] + ca, base[1] + sa)], fill=(225, 218, 208, 255), width=int(w * .075))
    pommel = (base[0] + math.cos(ang) * w * .2, base[1] + math.sin(ang) * w * .2)
    d.line([base, pommel], fill=(70, 62, 68, 255), width=int(w * .09))
    d.ellipse((pommel[0] - w * .05, pommel[1] - w * .05, pommel[0] + w * .05, pommel[1] + w * .05), fill=(225, 218, 208, 255))
    return im.resize((n, n), Image.LANCZOS)


def main():
    render = config.load().cache_dir / "img" / "Tang.png"
    big = render_icon(render)
    frames = [big.resize((s, s), Image.LANCZOS) for s in (256, 128, 64)] + [vector_icon(s) for s in (48, 32, 24, 16)]
    frames = [Image.frombytes(f.mode, f.size, f.tobytes()) for f in frames]  # pixels only
    out = ROOT / "packaging" / "bladesmith.ico"
    frames[0].save(out, format="ICO", append_images=frames[1:], sizes=[f.size for f in frames])
    print(out, sorted(Image.open(out).info["sizes"]))


if __name__ == "__main__":
    main()
