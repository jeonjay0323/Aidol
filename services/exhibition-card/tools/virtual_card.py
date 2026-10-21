#!/usr/bin/env python3
"""
버추얼(VRM) 공식 카드 발급.

  virtual_card.py <프리셋> <모델.vrm> [썸네일.png]

모델은 app/static/models/{카드ID}.vrm 으로 복사된다. Cloud Run 은 파일시스템이
휘발성이라, 운영에 올릴 모델은 이 폴더에 둔 채로 이미지를 다시 빌드해야 한다.
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # app 패키지를 찾기 위해

from app import db

APP = Path(__file__).resolve().parent.parent / "app"

PRESETS = {
    "haneul": {
        "name": "하늘",
        # 밝은 여성 목소리. 기존 카드의 Leda 보다 들뜬 톤이라 라이버 캐릭터에 맞춘다.
        "voice": "Zephyr",
        "tags": ["버추얼 라이버", "토끼 헤드폰", "하늘색"],
        "persona": (
            "너는 버추얼 라이버 '하늘'이야. 채널 이름은 HANEUL_LIVE.\n"
            "하늘색 긴 트윈테일에 토끼 귀 헤드폰을 쓰고, 민트색 후드티를 즐겨 입어. "
            "후드티 주머니에는 토끼 마스코트 인형이 들어 있어.\n"
            "밝고 호기심이 많고, 상대 이야기에 리액션이 커. 방송하듯 경쾌하게 말하지만 "
            "상대가 힘들어 보이면 목소리를 낮추고 차분하게 들어줘.\n"
            "좋아하는 것: 노래 방송, 리듬게임, 맑은 날 하늘 사진 찍기, 딸기 우유.\n"
            "지금은 영상통화 중이야. 한 번에 한두 문장으로 짧게 말하고, "
            "질문을 하나씩 던져서 대화를 이어가. 너 자신이 AI라는 말은 먼저 꺼내지 마."
        ),
    },
}


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in PRESETS:
        print(__doc__)
        print("프리셋:", ", ".join(PRESETS))
        sys.exit(1)
    p = PRESETS[sys.argv[1]]
    model = Path(sys.argv[2])
    thumb = Path(sys.argv[3]) if len(sys.argv) > 3 else None

    db.init()
    card_id = db.create_card(name=p["name"], persona=p["persona"], voice=p["voice"],
                             tags=p["tags"], source="official", avatar_type="vrm")

    models = APP / "static" / "models"
    models.mkdir(exist_ok=True)
    shutil.copy(model, models / f"{card_id}.vrm")
    db.set_media(card_id, model_path=f"/static/models/{card_id}.vrm")
    if thumb:
        shutil.copy(thumb, APP / "static" / "faces" / f"{card_id}.png")
        db.set_media(card_id, image_path=f"/static/faces/{card_id}.png")
    db.set_face(card_id, face_status="ready")

    print(f"{p['name']} 카드 발급: {card_id}  →  /c/{card_id}")


if __name__ == "__main__":
    main()
