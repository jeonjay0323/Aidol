#!/usr/bin/env python3
"""
공식 아이돌 표정 세트 만들기. 기본 사진 한 장을 기준으로 얼굴만 바꾼 사진을 뽑는다.

  make_expressions.py <slug> [표정 ...]        app/static/expr/<slug>/base.jpg 가 있어야 한다
  make_expressions.py haneul laugh             웃음만 다시

결과는 app/static/expr/<slug>/<표정>.jpg. 통화 중 아이돌이 하는 말에 따라 바뀐다
(app/expr.py · scan.html). 배포에 함께 실린다.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

import google.genai as genai  # noqa: E402
from google.genai import types  # noqa: E402
from PIL import Image  # noqa: E402
import io  # noqa: E402
from app import imagegen  # noqa: E402
from app.expr import EXPR_DIR, FACES  # noqa: E402

FACE = {
    "laugh":     "laughing out loud, eyes squeezed shut into happy upward arcs, mouth wide open in a big laugh, cheeks lifted",
    "surprised": "surprised and delighted, eyes wide open, eyebrows raised high, mouth open in a small round 'oh'",
    "thinking":  "thinking, eyes glancing up and to the side, lips pressed together and pushed slightly to one side, one eyebrow a little raised",
    # 실사에서 "blushing" 은 분홍 동그라미로 칠해져서, 색 대신 표정으로 수줍음을 낸다
    "shy":       "shy and flustered, a bashful closed-mouth smile, eyes looking slightly down and away, "
                 "only a very subtle natural warmth on the cheeks — no visible pink circles or painted blush",
    "sad":       "sympathetic and a little sad, eyebrows tilted up in the middle, soft downturned lips, gentle caring eyes",
}

RULES = ("Redraw this exact same {what} — same person, same face shape, same hair, same clothes, same pose, "
         "same framing, same lighting, same background, same {style}. "
         "Change only the facial expression: {face}. Keep everything else identical. "
         "No text, no border, no frame.")


def edit(src, prompt, aspect):
    """imagegen 과 같은 지역 순환. 429(한도)는 다른 지역으로, 다 막히면 잠시 쉬고 다시."""
    import random, time
    for round_ in range(4):
        for loc in random.sample(imagegen.LOCATIONS, len(imagegen.LOCATIONS)):
            try:
                client = genai.Client(vertexai=True, project=imagegen.project(), location=loc)
                r = client.models.generate_content(
                    model=imagegen.IMAGE_MODEL,
                    contents=[types.Part.from_bytes(data=src, mime_type="image/jpeg"), prompt],
                    config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"],
                                                       image_config=types.ImageConfig(aspect_ratio=aspect)),
                )
            except Exception as e:
                print(f"    {loc} 실패: {str(e)[:60]}", flush=True)
                continue
            for p in (r.candidates[0].content.parts if r.candidates else []) or []:
                if p.inline_data and p.inline_data.data:
                    return imagegen.to_jpeg(p.inline_data.data)
            raise RuntimeError("이미지가 오지 않았습니다(안전 필터?)")
        time.sleep(20 * (round_ + 1))
    raise RuntimeError("모든 지역이 막혔습니다")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    slug = sys.argv[1]
    d = EXPR_DIR / slug
    base = (d / "base.jpg").read_bytes()
    w, h = Image.open(io.BytesIO(base)).size
    aspect = "2:3" if abs(w / h - 2 / 3) < abs(w / h - 3 / 4) else "3:4"
    virtual = slug == "haneul"
    what = "anime character illustration" if virtual else "photograph of this person"
    style = "art style" if virtual else "photographic style and color grading"
    for name in sys.argv[2:] or FACES[1:]:
        if not sys.argv[2:] and (d / f"{name}.jpg").exists():
            continue   # 이름을 주지 않으면 이미 있는 표정은 건너뛴다
        print(f"  {slug} · {name} …", flush=True)
        out = edit(base, RULES.format(what=what, style=style, face=FACE[name]), aspect)
        (d / f"{name}.jpg").write_bytes(out)
    print("  끝")


if __name__ == "__main__":
    main()
