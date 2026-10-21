#!/usr/bin/env python3
"""
(시험) 만든 카드의 사진을 보고 기본 VRM 에 색만 입힌 3D 카드를 하나 더 발급한다.

  vrm_from_image.py <카드ID>

모델을 새로 만들지 않는다. 기본 모델(static/models/base-f.vrm — pixiv 샘플) 하나를
모든 카드가 같이 쓰고, Gemini 가 사진에서 읽은 머리 · 눈 · 상의 · 하의 · 신발 색을
꾸미기(custom.colors)로 넣는다. 브라우저가 통화 때 텍스처를 다시 칠한다.
Simli 등록이 필요 없으므로 발급 즉시 영상통화가 된다. 원래 카드는 건드리지 않는다.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

import google.genai as genai  # noqa: E402
from google.genai import types  # noqa: E402
from app import db, imagegen  # noqa: E402

BASE_MODEL = "/static/models/base-f.vrm"
PARTS = ["hair", "eye", "top", "bottom", "shoes"]
ASK = (
    "This is a character illustration. Return the main colour of each part as JSON with hex values: "
    '{"hair": "#rrggbb", "eye": "#rrggbb", "top": "#rrggbb", "bottom": "#rrggbb", "shoes": "#rrggbb"}. '
    "top = upper-body clothing, bottom = skirt or trousers. "
    "If a part is not visible, pick a colour that matches the outfit. JSON only."
)


def read_colors(jpeg):
    client = genai.Client(vertexai=True, project=imagegen.project(), location="us-central1")
    r = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[types.Part.from_bytes(data=jpeg, mime_type="image/jpeg"), ASK],
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    raw = json.loads(r.text)
    return {k: v for k, v in raw.items()
            if k in PARTS and isinstance(v, str) and re.match(r"^#[0-9a-fA-F]{6}$", v)}


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    db.init()
    src = db.get_card(sys.argv[1])
    if not src:
        sys.exit("카드가 없습니다")
    jpeg = db.get_thumb(src["card_id"])
    if not jpeg:
        sys.exit("사진(썸네일)이 없는 카드입니다")
    if not (ROOT / "app" / BASE_MODEL.lstrip("/")).exists():
        sys.exit(f"기본 모델이 없습니다: app{BASE_MODEL}")

    colors = read_colors(jpeg)
    print("읽은 색", colors)
    cid = db.create_card(name=src["name"], persona=src["persona"], voice=src["voice"],
                         tags=src["tags"], stats=src["stats"], source=src["source"],
                         avatar_type="vrm")
    db.set_media(cid, model_path=BASE_MODEL)
    db.set_thumb(cid, jpeg)   # 카드 · 전시에는 원래 사진을 그대로 쓴다
    db.set_custom(cid, {"colors": colors, "speech": None, "callme": "", "note": ""})
    db.set_face(cid, face_status="ready")
    print(f"3D 카드 {cid}  →  /c/{cid}")


if __name__ == "__main__":
    main()
