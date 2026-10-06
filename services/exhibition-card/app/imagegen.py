"""
관람객이 고른 조합 + 직접 쓴 프롬프트로 카드 사진을 만든다.

실물   gen/normal.py · gen/epic.py 의 프롬프트 조립을 그대로 쓴다 (레퍼런스 없이 텍스트로).
       gen/ 은 tools/image-generator 의 사본이다. 원본을 고치면 다시 복사한다.
버추얼 애니메이션 일러스트. 프롬프트는 여기서 조립한다.

Simli 등록은 하지 않는다. 생성 → 확인 → 발급 → 인쇄로 바로 간다.
라벨 용지가 60×40mm 라 사진은 세로 2:3(40×60) 으로 뽑고, 인쇄할 때 90° 돌린다.
"""
import io
import logging
import os
import random
import sys
from pathlib import Path

import google.genai as genai
from google.genai import types
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent / "gen"))  # epic.py 가 `import normal` 을 쓴다
import normal as N  # noqa: E402
import epic as E    # noqa: E402

# main.py 가 .env 를 읽기 전에 이 모듈이 import 되므로, 프로젝트는 호출할 때 읽는다
def project():
    return os.getenv("GCP_PROJECT", "project-d4a769de-d13f-4a6a-a22")


IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gemini-2.5-flash-image")
# 생성기와 같은 순환. 429 가 나면 다음 지역으로 넘어간다.
LOCATIONS = ["us-central1", "us-east4", "us-west1", "us-west4"]
LABEL_ASPECT = "2:3"   # 라벨 40×60mm 세로

log = logging.getLogger("imagegen")


# ── 버추얼 ───────────────────────────────────────────────
MOODS = {
    "fresh":  "bright and refreshing, clear summer-sky energy, a wide open smile",
    "dreamy": "soft and dreamy, gentle half-smile, sparkles of light around",
    "dark":   "cool and dark, a confident sharp gaze, subtle neon rim light",
    "cute":   "playful and cute, a wink or a puffed cheek, lively pose",
    "chic":   "chic and calm, poised expression, elegant and minimal",
}
# 헥스코드는 그림에 글자로 박혀서 서술어로 넘긴다 (virtual.py 와 같은 이유)
HAIR = {
    "pink": "pastel pink", "lilac": "soft lilac", "sky": "pale sky blue",
    "blonde": "honey blonde", "black": "glossy black", "silver": "silvery white",
}

VIRTUAL_STYLE = (
    "A high-quality anime-style illustration of a Korean virtual idol (VTuber) character, "
    "{subject}, polished cel shading with soft gradients, clean confident line art, "
    "large expressive eyes, the look of an official VTuber debut key visual. "
    "Mood: {mood}. Hair colour: {hair}. "
    "Framing: vertical portrait composition, from the head down to the waist, facing the viewer, "
    "the head in the upper third with a little space above it. "
    "Background: a simple soft pastel backdrop with light graphic shapes that does not compete with the character. "
)
VIRTUAL_RULES = (
    " Do not draw any text, letters, logos, signatures, watermarks or UI elements. "
    "Full-bleed artwork that fills the whole canvas edge to edge — no border, frame or inset panel. "
    "A single character only. Keep it wholesome: a modest stage outfit with no cleavage or bare midriff."
)


def virtual_prompt(gender, mood, hair, add):
    subject = "a girl in her early twenties" if gender == "f" else "a boy in his early twenties"
    p = VIRTUAL_STYLE.format(subject=subject, mood=MOODS.get(mood, MOODS["fresh"]),
                             hair=HAIR.get(hair, HAIR["sky"]))
    if add:
        p += f"Additional requests from the creator (follow them): {add}."
    return p + VIRTUAL_RULES


# ── 실물 ─────────────────────────────────────────────────
def real_prompt(gender, grade, look, add, rng):
    add = f"Additional requests from the creator (follow them): {add}." if add else None
    if grade == "epic":
        return E.build_prompt(look, rng, refs=[], gender=gender, add=add), LABEL_ASPECT
    # profile 은 가로컷이라 세로 화보컷(editorial) 프롬프트를 쓴다
    return N.build_prompt(look, rng, refs=[], mode="editorial", add=add, gender=gender), LABEL_ASPECT


def build(spec):
    """spec → (프롬프트, 비율). 잘못된 값은 ValueError."""
    gender = spec.get("gender")
    if gender not in ("m", "f"):
        raise ValueError("성별을 골라주세요")
    add = str(spec.get("prompt") or "").strip()[:300] or None
    if spec.get("kind") == "virtual":
        return virtual_prompt(gender, spec.get("mood"), spec.get("hair"), add), LABEL_ASPECT
    grade, look = spec.get("grade"), spec.get("look")
    pool = E.SPECIES if grade == "epic" else N.PRESETS
    if look not in pool:
        raise ValueError("얼굴상을 골라주세요")
    return real_prompt(gender, grade, look, add, random.Random())


def generate(spec):
    """JPEG 바이트를 돌려준다. 썸네일 저장소(700KB) 에 그대로 들어가는 크기로."""
    prompt, aspect = build(spec)
    err = None
    for loc in random.sample(LOCATIONS, len(LOCATIONS)):
        try:
            client = genai.Client(vertexai=True, project=project(), location=loc)
            r = client.models.generate_content(
                model=IMAGE_MODEL, contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                    image_config=types.ImageConfig(aspect_ratio=aspect),
                ),
            )
            for part in (r.candidates[0].content.parts if r.candidates else []) or []:
                if part.inline_data and part.inline_data.data:
                    return to_jpeg(part.inline_data.data, trim=spec.get("kind") == "virtual")
            # 안전 필터에 걸리면 이미지 없이 돌아온다. 다른 지역도 같으니 바로 멈춘다.
            raise RuntimeError("이미지를 만들지 못했어요. 프롬프트를 바꿔서 다시 해보세요.")
        except RuntimeError:
            raise
        except Exception as e:
            err = e
            log.warning(f"이미지 생성 실패 ({loc}): {e}")
    raise RuntimeError(f"생성 서버가 바빠요. 잠시 후 다시 해보세요. ({err})")


def trim_frame(img, ratio=2 / 3):
    """일러스트는 프롬프트로 막아도 단색 테두리를 그릴 때가 있다. 라벨에 띠가 남지 않게
    네 모서리 색이 같으면 그 색과 다른 영역만 남기고, 비율을 다시 2:3 으로 맞춘다."""
    from PIL import ImageChops
    w, h = img.size
    corners = [img.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
    if max(max(abs(a - b) for a, b in zip(c, corners[0])) for c in corners) > 24:
        return img
    diff = ImageChops.difference(img, Image.new("RGB", img.size, corners[0])).convert("L")
    box = diff.point(lambda v: 255 if v > 40 else 0).getbbox()
    if not box:
        return img
    l, t, r, b = box
    # 테두리가 아니라 배경일 수도 있다 — 가장자리에서 12% 넘게 들어가면 손대지 않는다
    if l > w * .12 or t > h * .12 or w - r > w * .12 or h - b > h * .12 or box == (0, 0, w, h):
        return img
    pad = 4   # 테두리 안쪽 경계선(안티앨리어싱)까지 걷어낸다
    img = img.crop((l + pad, t + pad, r - pad, b - pad))
    cw, ch = img.size
    if cw / ch > ratio:
        nw = int(ch * ratio)
        img = img.crop(((cw - nw) // 2, 0, (cw - nw) // 2 + nw, ch))
    else:
        nh = int(cw / ratio)
        img = img.crop((0, 0, cw, nh))   # 머리가 잘리지 않게 위를 남긴다
    return img


def to_jpeg(data, max_side=1280, trim=False):
    img = Image.open(io.BytesIO(data)).convert("RGB")
    if trim:
        img = trim_frame(img)
    img.thumbnail((max_side, max_side))
    for q in (90, 82, 74):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=q, optimize=True)
        if buf.tell() <= 650_000:
            break
    return buf.getvalue()
