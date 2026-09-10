"""통화 중 활성 세션 수를 계속 찍어 최댓값을 남긴다. 동시 세션 허용 여부 확인용."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # app 패키지를 찾기 위해

import sys, time
from datetime import datetime
from app import simli

def main():
    seconds = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    peak, end = 0, time.time() + seconds
    print(f"{seconds}초 동안 관찰합니다. 지금 통화 두 개를 열어주세요.\n")
    while time.time() < end:
        try:
            n = simli.active_sessions()
        except Exception as e:
            print(f"  조회 실패: {e}"); time.sleep(3); continue
        peak = max(peak, n)
        print(f"[{datetime.now():%H:%M:%S}] 활성 {n}  (최대 {peak})", flush=True)
        time.sleep(3)

    print(f"\n최대 동시 세션: {peak}")
    print("→ 2 이상: 동시 세션 허용, 멀티콜 구현 가능" if peak >= 2
          else "→ 1 이하: 동시 세션 제한이거나 통화가 안 열렸을 수 있음")


if __name__ == "__main__":
    main()
