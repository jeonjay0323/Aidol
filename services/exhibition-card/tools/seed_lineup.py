#!/usr/bin/env python3
"""
통화 페이지의 공식 아이돌 5명 중 없는 사람을 발급한다.

  seed_lineup.py <서버 주소> [이름 ...]
  seed_lineup.py http://localhost:8800            # 로컬
  seed_lineup.py https://aidol-card-…run.app 도하  # 운영, 도하만
  --no-face 를 붙이면 Simli 등록을 건너뛴다(로컬 시험용, 음성 통화 카드가 된다)

하루 · 시온(사진) · 하늘(VRM) 은 이미 있다. 여기서는 사진 카드만 만든다.
사진을 Gemini 로 뽑아 서버 /api/cards 에 공식 카드로 올리고 Simli 얼굴 등록까지 건다
(완료까지 최대 8시간 — 그동안은 음성 통화). 서버는 사진을 static/faces/ 에 쓰는데
Cloud Run 은 재시작하면 사라지므로, 같은 파일을 로컬 app/static/faces/ 에도 남겨
다음 배포에 실리게 한다.
"""
import io
import json
import random
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

from PIL import Image  # noqa: E402
from app import imagegen  # noqa: E402
N = imagegen.N   # gen/normal.py — imagegen 이 경로를 잡아 불러온 것을 그대로 쓴다

TAIL = "팬이 전화한 것처럼 편하게, 짧고 자연스럽게 반말로 대화해."

IDOLS = {
    "도하": {
        "gender": "m", "look": "dog", "voice": "Fenrir",
        "tags": ["랩", "강아지상", "막내"],
        "persona": (
            "너는 K-pop 아이돌 연습생 도하야. 20살 한국 남자고 팀의 막내 래퍼야. "
            "20대 초반의 밝고 경쾌한 목소리로 말해. 웃음이 많고 리액션이 커서 상대 이야기에 크게 반응해. "
            "상대의 오늘 하루가 어땠는지 꼭 물어봐. " + TAIL
        ),
    },
    "린": {
        "gender": "f", "look": "deer", "voice": "Aoede",
        "tags": ["보컬", "사슴상", "몽환"],
        "persona": (
            "너는 K-pop 아이돌 연습생 린이야. 22살 한국 여자고 몽환적인 음색의 보컬이야. "
            "20대 초반의 부드럽고 맑은 목소리로 말해. 목소리를 억지로 낮추지 마. "
            "말수는 적고 조용하지만 상대 이야기를 끝까지 듣고, 기억해 뒀다가 다시 물어봐. " + TAIL
        ),
    },
}

# Simli 는 정면 얼굴이 필요하다. 기존 공식 카드(하루 · 시온)와 같은 3:4 화보컷으로 맞춘다.
FRONT = ("Looking straight into the camera with the face turned fully toward the viewer, "
         "both eyes clearly visible, mouth gently closed, hands away from the face.")


def make_photo(p):
    prompt = N.build_prompt(p["look"], random.Random(), refs=[], mode="editorial",
                            gender=p["gender"], add=FRONT)
    return imagegen.render(prompt, "3:4")


def to_png(raw):
    buf = io.BytesIO()
    Image.open(io.BytesIO(raw)).convert("RGB").save(buf, "PNG", optimize=True)
    return buf.getvalue()


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    face = "--no-face" not in sys.argv
    base = args[0].rstrip("/")
    want = args[1:] or list(IDOLS)

    have = {c["name"] for c in requests.get(f"{base}/api/cards", params={"source": "official"},
                                            timeout=30).json()}
    for name in want:
        if name not in IDOLS:
            print(f"  모르는 이름: {name}")
            continue
        if name in have:
            print(f"  건너뜀 (이미 있음) {name}")
            continue
        p = IDOLS[name]
        print(f"  {name} 사진 생성 중…")
        raw = make_photo(p)
        # 얼굴 등록을 하면 서버가 PNG 를 static/faces 에 쓰고, 안 하면 JPEG 을 DB 썸네일로 둔다
        image = (f"{name}.png", to_png(raw), "image/png") if face else \
                (f"{name}.jpg", imagegen.to_jpeg(raw), "image/jpeg")
        r = requests.post(f"{base}/api/cards", data={
            "name": name, "persona": p["persona"], "voice": p["voice"],
            "tags": json.dumps(p["tags"], ensure_ascii=False),
            "stats": "{}", "source": "official", "register_face": "true" if face else "false",
        }, files={"image": image}, timeout=180)
        r.raise_for_status()
        j = r.json()
        print(f"  {name} → {j['cardId']} · 얼굴 {j['faceStatus']} {j['warnings'] or ''}")
        if face:
            out = ROOT / "app" / "static" / "faces" / f"{j['cardId']}.png"
            out.write_bytes(image[1])
            print(f"    사진 {out.relative_to(ROOT)} — 다음 배포에 실린다")


if __name__ == "__main__":
    main()
