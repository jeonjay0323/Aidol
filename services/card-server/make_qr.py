#!/usr/bin/env python3
"""카드 QR 생성.

주소는 Cloud Run 고정 도메인을 쓴다. 인쇄물이라 주소가 바뀌면 안 되므로
로컬 IP 를 잡던 이전 방식은 폐기했다.

    python3 make_qr.py                 # DB 의 모든 카드
    python3 make_qr.py G6CNSAAA        # 특정 카드만
    python3 make_qr.py --base http://localhost:8000   # 로컬 테스트용
"""
import os
import sys
from pathlib import Path

import segno

BASE_URL = "https://aidol-card-294218538342.asia-northeast3.run.app"
HERE = Path(__file__).parent
OUT = HERE / "qr"


def main():
    argv = sys.argv[1:]
    base = BASE_URL
    if "--base" in argv:
        i = argv.index("--base")
        base = argv[i + 1].rstrip("/")
        del argv[i:i + 2]

    os.environ.setdefault("DB_BACKEND", "firestore")
    import db

    ids = argv or [c["card_id"] for c in db.list_cards()]
    if not ids:
        print("카드가 없습니다.")
        return

    OUT.mkdir(exist_ok=True)
    for cid in ids:
        card = db.get_card(cid)
        if not card:
            print(f"  {cid}  — DB 에 없음, 건너뜀")
            continue
        url = f"{base}/c/{cid}"
        # error='m' = 15% 복원. 인쇄 후 긁힘/조명 반사에 견디는 최소선.
        qr = segno.make(url, error="m")
        path = OUT / f"{cid}.png"
        qr.save(path, scale=20, border=2, dark="#2b1d14", light="#f2e6d2")
        print(f"  {cid}  {card['name']:6}  v{qr.version}  {url}")

    print(f"\n저장 → {OUT}")


if __name__ == "__main__":
    main()
