"""
얼굴 등록 상태를 주기적으로 확인해 DB에 반영한다.
등록이 최대 8시간 걸리므로 서버와 분리된 프로세스로 돌린다.

  python worker.py [확인주기_분]
"""
import sys
import time
from datetime import datetime

import db
import simli

READY_WORDS = ("complete", "ready", "success", "done")
FAIL_WORDS = ("fail", "error")


def tick():
    pending = db.pending_faces()
    if not pending:
        return 0

    for card in pending:
        fid = card.get("face_id")
        if not fid:
            continue
        try:
            status, raw = simli.generation_status(fid)
        except Exception as e:
            print(f"  {card['card_id']} 조회 실패: {e}")
            continue

        s = str(status).lower()
        if any(w in s for w in READY_WORDS):
            db.set_face(card["card_id"], face_status="ready")
            print(f"  ✓ {card['card_id']} ({card['name']}) 준비 완료")
        elif any(w in s for w in FAIL_WORDS):
            db.set_face(card["card_id"], face_status="failed")
            print(f"  ✗ {card['card_id']} ({card['name']}) 실패 — 음성 통화로 폴백")
    return len(pending)


if __name__ == "__main__":
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    print(f"워커 시작 — {interval}분 주기")
    while True:
        n = tick()
        print(f"[{datetime.now():%H:%M:%S}] 대기중 {n}건")
        time.sleep(interval * 60)
