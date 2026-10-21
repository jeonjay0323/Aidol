"""
공식 아이돌 표정 세트.

app/static/expr/<slug>/ 에 base.jpg 와 표정 사진(laugh · surprised · thinking · shy · sad)이 있으면
그 아이돌은 통화할 때 큰 사진으로 나오고, 아이돌이 하는 말에 따라 표정이 바뀐다(scan.html).
단 Simli 얼굴이 준비된 사진 카드(하루 · 시온)는 영상 통화가 우선이라 표정 세트를 쓰지 않는다.
VRM(하늘)은 표정 세트가 대신한다.
사진은 배포에 실리는 파일이라 운영 DB 를 건드리지 않는다. 만드는 도구는 tools/make_expressions.py.
"""
from pathlib import Path

EXPR_DIR = Path(__file__).parent / "static" / "expr"
FACES = ["base", "laugh", "surprised", "thinking", "shy", "sad"]

# 공식 카드 이름 → 폴더. 로컬 · 운영의 카드 id 가 달라 이름으로 찾는다
SLUGS = {"하루": "haru", "시온": "sion", "하늘": "haneul", "도하": "doha", "린": "rin"}


def of(card):
    """{표정: URL} 또는 None. 공식 카드만."""
    if not card or card.get("source") != "official":
        return None
    slug = SLUGS.get(card.get("name"))
    if not slug or not (EXPR_DIR / slug / "base.jpg").exists():
        return None
    if card.get("avatar_type") != "vrm" and card.get("face_id") and card.get("face_status") == "ready":
        return None   # Simli 영상 통화가 된다
    return {f: f"/static/expr/{slug}/{f}.jpg" for f in FACES if (EXPR_DIR / slug / f"{f}.jpg").exists()}
