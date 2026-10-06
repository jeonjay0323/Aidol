"""
라벨을 이미지 한 장으로 그린다 — 라벨 프린터 앱(Aiyin 등)에 넘기기 위해.

블루투스 라벨 프린터는 AirPrint 가 안 돼서 브라우저 인쇄 창으로는 못 뽑는다.
이 이미지를 아이패드 공유 시트로 앱에 넘기거나 사진첩에 저장해 앱에서 불러온다.
디자인은 label.html 과 같다 — 세로 40×60mm 로 그리고 용지(가로 60×40mm)에 맞게 눕힌다.

mono=True 면 흑백 감열 프린터용으로 회색조 + 디더링한다.
"""
import io
from pathlib import Path

import segno
from PIL import Image, ImageDraw, ImageFont, ImageOps

FONTS = Path(__file__).parent / "static" / "fonts"
DPI = 300                                        # 앱 공유용. 블루투스 직접 인쇄는 프린터 해상도(대개 203)
PAPER = (255, 255, 255)                          # label.html --paper
INK = (0, 0, 0)                                  # --ink


MM = W = H = None


def _set_dpi(dpi):
    global MM, W, H
    MM = dpi / 25.4
    W, H = round(40 * MM), round(60 * MM)        # 세로 디자인 (300dpi 472 × 709, 203dpi 320 × 480)


def font(weight, px):
    name = {"bold": "Paperlogy-7Bold.ttf", "medium": "Paperlogy-5Medium.ttf"}[weight]
    return ImageFont.truetype(str(FONTS / name), px)


def mm(v):
    return round(v * MM)


def cover(img, w, h, y_focus=0.2):
    """object-fit:cover · object-position:50% 20%"""
    iw, ih = img.size
    s = max(w / iw, h / ih)
    img = img.resize((round(iw * s), round(ih * s)), Image.LANCZOS)
    iw, ih = img.size
    x = (iw - w) // 2
    y = round((ih - h) * y_focus)
    return img.crop((x, y, x + w, y + h))


def fit_text(draw, text, weight, px, max_w):
    """한 줄에 들어갈 때까지 글자를 줄인다"""
    while px > 10:
        f = font(weight, px)
        if draw.textlength(text, font=f) <= max_w:
            return f
        px -= 2
    return font(weight, px)


def render(photo_bytes, name, tags, card_id, scan_url, mono=False, dpi=DPI):
    _set_dpi(dpi)
    label = Image.new("RGB", (W, H), INK)
    if photo_bytes:
        photo = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
        label.paste(cover(photo, W, H), (0, 0))

    # 아래쪽을 어둡게 — 어떤 사진이든 이름이 읽히게 (label.html .foot 그라데이션)
    shade = Image.new("L", (1, H), 0)
    top = H - mm(26)
    for y in range(top, H):
        t = (y - top) / (H - top)
        shade.putpixel((0, y), round(255 * (0.55 * min(t / 0.4, 1) + 0.30 * max(t - 0.4, 0) / 0.6)))
    label = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), label, shade.resize((W, H)))

    d = ImageDraw.Draw(label)
    pad = mm(1.6)

    # 위: 칩 + 카드 번호
    chip_f = font("bold", mm(2.2))
    tw = d.textlength("LUKIDS", font=chip_f)
    d.rounded_rectangle((pad, pad, pad + tw + mm(2.4), pad + mm(3.6)), radius=mm(0.8), fill=INK)
    d.text((pad + mm(1.2), pad + mm(1.8)), "LUKIDS", font=chip_f, fill=PAPER, anchor="lm")
    ser_f = font("bold", mm(1.8))
    d.text((W - pad, pad + mm(1.8)), card_id, font=ser_f, fill=(255, 255, 255), anchor="rm",
           stroke_width=2, stroke_fill=(0, 0, 0))

    # 아래: QR (흰 바탕) + 이름 · 태그
    q = mm(16)
    qr = segno.make(scan_url, error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="png", scale=10, border=2, dark="#000000", light="#ffffff")
    qr_img = Image.open(buf).convert("RGB").resize((q, q), Image.NEAREST)
    cap = mm(2.2)                                   # QR 아래 "스캔하고 통화하세요"
    qx, qy = W - pad - q, H - pad - q - cap
    d.rounded_rectangle((qx - mm(0.5), qy - mm(0.5), qx + q + mm(0.5), qy + q + cap + mm(0.3)),
                        radius=mm(0.6), fill=(255, 255, 255))
    label.paste(qr_img, (qx, qy))
    cap_f = fit_text(d, "스캔하고 통화하세요", "bold", mm(1.6), q)
    d.text((qx + q / 2, qy + q + cap / 2), "스캔하고 통화하세요", font=cap_f, fill=(0, 0, 0), anchor="mm")

    text_w = qx - pad - mm(1.4)
    name_f = fit_text(d, name, "bold", mm(6.4), text_w)
    tag_text = " · ".join(tags or [])
    tag_f = fit_text(d, tag_text, "medium", mm(1.9), text_w)
    ty = H - pad
    d.text((pad, ty), tag_text, font=tag_f, fill=PAPER, anchor="ls")
    d.text((pad, ty - mm(3.0)), name, font=name_f, fill=PAPER, anchor="ls",
           stroke_width=mm(0.6), stroke_fill=INK)

    # 용지에 맞게 눕힌다 — label.html 의 rotate(-90deg) 와 같은 방향(카드 윗면이 용지 왼쪽)
    out = label.rotate(90, expand=True)
    if mono:
        g = ImageOps.autocontrast(out.convert("L"), cutoff=1)
        g = g.point(lambda v: round(255 * (v / 255) ** 0.65))   # 감열지는 어둡게 나와서 중간톤을 밝힌다
        out = g.convert("1")                                     # 플로이드-스타인버그 디더링
    buf = io.BytesIO()
    out.save(buf, "PNG", dpi=(dpi, dpi))
    return buf.getvalue()
