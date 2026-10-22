"""
4×6 인쇄 카드를 PNG 한 장으로 그린다 (1181×1748, 300dpi).
아이폰 사파리는 웹 페이지를 인쇄할 때 웹 글꼴 · 효과가 빠지고 @page 크기를 무시해 여백이 생긴다.
그래서 인쇄는 이 이미지로 한다 — 사진첩에 저장해 사진처럼 뽑으면 테두리 없이 꽉 찬다.

고정된 부분(배경 · 프레임 · 등급 · 아이콘)은 label.html 을 크롬으로 찍은 레이어(static/print/<등급>/base · over.png,
tools/make_print_layers.py)를 쓰고, 여기서는 사진 · 이름 · 영문 이름 · 한마디 · 다정함 · QR 만 같은 자리에 얹는다.
자리는 label.html ?layer=geom 으로 잰 값이다.
"""
import io
from pathlib import Path

import segno
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

HERE = Path(__file__).parent
PRINT = HERE / "static" / "print"
FONTS = HERE / "static" / "fonts"
W, H = 1181, 1748
DPI = 300

INK = {"sss": "#5332d8", "s": "#db15a3", "a": "#3475ff", "n": "#595959"}
BAR = {"sss": "#cfafff", "s": "#ff8bde", "a": "#89c8ff", "n": "#d9d9d9"}

PHOTO = (84, 193, 1013, 846)   # 모서리 40px 를 깎는다
NAME = (84, 1105, 94)          # x, 위, 줄 높이
EN = (84, 1223, 52)
MSG = (84, 1315, 48, 440)      # x, 위, 줄 높이, 폭
STAT = (1065, 1606, 32)
FILL = (292, 1606.5, 31)       # x, 위, 높이 — 폭은 다정함 × 7.6 (90 → 684px)
QR = (832, 1140, 220)


def _font(name, size):
    return ImageFont.truetype(str(FONTS / name), size)


def _line(draw, xy, text, font, fill, box):
    """CSS line-height 상자 안에 글자를 놓는다 — 위아래 여백을 반씩 (half-leading)."""
    a, d = font.getmetrics()
    x, top = xy
    draw.text((x, top + (box - a - d) / 2 + a), text, font=font, fill=fill, anchor="ls")


def _wrap(text, font, width):
    """줄바꿈은 그대로 두고, 폭을 넘으면 띄어쓰기에서 끊는다 (word-break: keep-all)."""
    out = []
    for para in text.split("\n"):
        line = ""
        for word in para.split(" "):
            test = f"{line} {word}".strip()
            if line and font.getlength(test) > width:
                out.append(line)
                line = word
            else:
                line = test
        out.append(line)
    return out


def _chamfer(w, h, c, scale=4):
    """모서리를 깎은 사각형 마스크. 크게 그려 줄여서 사선을 매끄럽게."""
    m = Image.new("L", (w * scale, h * scale), 0)
    c *= scale
    W_, H_ = w * scale, h * scale
    ImageDraw.Draw(m).polygon([(c, 0), (W_ - c, 0), (W_, c), (W_, H_ - c), (W_ - c, H_), (c, H_), (0, H_ - c), (0, c)],
                              fill=255)
    return m.resize((w, h), Image.LANCZOS)


def _qr(url, size):
    qr = segno.make(url, error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="png", scale=1, border=2, dark="#000000", light="#ffffff")
    return Image.open(buf).convert("RGB").resize((size, size), Image.NEAREST)


def render(v, name, photo, qr_url):
    """v: card_print.values() — grade · en · msg · stat. photo: 사진 바이트(없으면 회색)."""
    g = v["grade"]
    card = Image.open(PRINT / g / "base.png").convert("RGBA")

    # 사진 — object-fit: cover, 위쪽 22% 기준 (얼굴이 잘리지 않게)
    x, y, w, h = PHOTO
    if photo:
        img = ImageOps.fit(Image.open(io.BytesIO(photo)).convert("RGB"), (w, h), Image.LANCZOS, centering=(0.5, 0.22))
    else:
        img = Image.new("RGB", (w, h), "#d9d9d9")
    card.paste(img, (x, y), _chamfer(w, h, 40))

    card.alpha_composite(Image.open(PRINT / g / "over.png").convert("RGBA"))

    # 글자 — 이름 · 영문 이름 · 한마디는 흰 빛을 두른다 (drop-shadow 0 0 6px rgba(255,255,255,.9))
    ink = INK[g]
    text = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(text)
    _line(d, NAME[:2], name, _font("Paperlogy-7Bold.ttf", 80), ink, NAME[2])
    _line(d, EN[:2], v["en"].upper(), _font("IBMPlexMono-Regular.ttf", 40), ink, EN[2])
    mf = _font("neodgm.ttf", 40)
    for i, ln in enumerate(_wrap(v["msg"].upper(), mf, MSG[3])[:4]):
        _line(d, (MSG[0], MSG[1] + i * MSG[2]), ln, mf, ink, MSG[2])
    glow = Image.new("RGBA", (W, H), (255, 255, 255, 0))
    glow.putalpha(text.getchannel("A").filter(ImageFilter.GaussianBlur(3)).point(lambda a: round(a * 0.9)))
    card.alpha_composite(glow)
    card.alpha_composite(text)

    d = ImageDraw.Draw(card)
    _line(d, STAT[:2], str(v["stat"]), _font("neodgm.ttf", 32), ink, STAT[2])
    fx, fy, fh = FILL
    fw = round(v["stat"] * 7.6)
    if fw > 0:
        d.rounded_rectangle((fx, fy, fx + fw, fy + fh), radius=fh / 2, fill=BAR[g])

    qx, qy, qs = QR
    card.paste(_qr(qr_url, qs), (qx, qy))

    out = io.BytesIO()
    card.convert("RGB").save(out, "PNG", dpi=(DPI, DPI))
    return out.getvalue()
