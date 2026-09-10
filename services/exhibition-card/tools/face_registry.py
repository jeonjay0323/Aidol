#!/usr/bin/env python3
"""
Simli legacy face 등록 · 상태 추적.

등록은 최대 8시간이 걸리므로 등록과 조회를 분리했다.
진행 상태는 faces.json에 즉시 기록되니 스크립트를 꺼도 안전하다.

  register <이미지폴더>   폴더의 이미지를 모두 등록
  status                 등록한 얼굴들의 상태 확인 · 갱신
  watch [분]             완료될 때까지 주기적으로 확인 (기본 10분)
  faces                  Simli 계정의 전체 얼굴 목록
  sessions               현재 활성 세션 수

키는 .env의 SIMLI_API_KEY에서 읽는다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # app 패키지를 찾기 위해

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
import os

HERE = Path(__file__).parent.parent
STATE = HERE / "faces.json"
API = "https://api.simli.ai"
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}

load_dotenv(HERE / ".env")
KEY = os.getenv("SIMLI_API_KEY", "")


def headers():
    if not KEY:
        sys.exit("SIMLI_API_KEY가 없습니다. .env에 넣어주세요.")
    return {"x-simli-api-key": KEY}


def now():
    return datetime.now(timezone.utc).isoformat()


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"faces": []}


def save_state(state):
    STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False))


def all_face_ids():
    """계정에 등록된 얼굴 id 집합. POST 응답에 id가 없을 때 diff로 찾아내기 위함."""
    r = requests.get(f"{API}/faces", headers=headers(), timeout=30)
    r.raise_for_status()
    return {f["id"] for f in r.json()}


def dig_face_id(payload):
    """응답 스키마가 문서에 {}로만 되어 있어, 흔한 키 이름을 모두 훑는다."""
    if not isinstance(payload, dict):
        return None
    for k in ("character_uid", "face_id", "faceId", "id", "faceID"):
        if payload.get(k):
            return payload[k]
    return None


# ── register ──────────────────────────────────────────────
def cmd_register(image_dir):
    images = sorted(p for p in Path(image_dir).iterdir() if p.suffix.lower() in IMAGE_EXT)
    if not images:
        sys.exit(f"{image_dir}에 이미지가 없습니다.")

    state = load_state()
    done = {f["image"] for f in state["faces"]}

    print(f"{len(images)}장 발견\n")
    before = all_face_ids()

    for img in images:
        if str(img) in done:
            print(f"  건너뜀 (이미 등록) {img.name}")
            continue

        name = img.stem
        with open(img, "rb") as fh:
            r = requests.post(
                f"{API}/faces/legacy",
                headers=headers(),
                params={"face_name": name, "characterVersion": "1.5"},
                files={"image": (img.name, fh, "image/png")},
                timeout=120,
            )

        entry = {
            "name": name,
            "image": str(img),
            "faceId": None,
            "status": "submitted",
            "submittedAt": now(),
            "readyAt": None,
            "httpStatus": r.status_code,
        }

        try:
            body = r.json()
        except ValueError:
            body = {"_raw": r.text[:500]}
        entry["submitResponse"] = body

        if r.status_code >= 400:
            entry["status"] = "failed"
            print(f"  ✗ {img.name} — HTTP {r.status_code}: {body}")
        else:
            fid = dig_face_id(body)
            if not fid:
                # 응답에 id가 없으면 목록 diff로 찾는다
                time.sleep(2)
                new = all_face_ids() - before
                if len(new) == 1:
                    fid = new.pop()
                    before = all_face_ids()
                elif new:
                    entry["_ambiguous"] = sorted(new)
            entry["faceId"] = fid
            print(f"  ✓ {img.name} → {fid or '(id 미확인 — status로 재확인)'}")

        state["faces"].append(entry)
        save_state(state)

    print(f"\n{STATE} 에 기록했습니다.")
    print("등록에 최대 8시간이 걸립니다. `status` 또는 `watch`로 확인하세요.")


# ── status ────────────────────────────────────────────────
def cmd_status():
    state = load_state()
    if not state["faces"]:
        sys.exit("등록된 얼굴이 없습니다. 먼저 register를 실행하세요.")

    live = all_face_ids()
    changed = False

    for f in state["faces"]:
        if f["status"] in ("ready", "failed"):
            continue
        fid = f.get("faceId")

        # id를 아직 못 찾았다면 목록에서 이름으로 다시 시도
        if not fid:
            f["status"] = "unknown"
            continue

        r = requests.get(
            f"{API}/faces/legacy/generation_status",
            headers=headers(),
            params={"face_id": fid},
            timeout=30,
        )
        try:
            body = r.json()
        except ValueError:
            body = {"_raw": r.text[:300]}
        f["lastStatusResponse"] = body

        text = json.dumps(body).lower()
        if any(w in text for w in ("complete", "ready", "success", "done")):
            f["status"] = "ready"
            f["readyAt"] = now()
            changed = True
        elif any(w in text for w in ("fail", "error")):
            f["status"] = "failed"
            changed = True
        elif fid in live:
            f["status"] = "processing"
        changed = True

    save_state(state)

    print(f"{'이름':<14}{'상태':<12}{'경과':<10}faceId")
    print("─" * 76)
    for f in state["faces"]:
        submitted = datetime.fromisoformat(f["submittedAt"])
        end = datetime.fromisoformat(f["readyAt"]) if f.get("readyAt") else datetime.now(timezone.utc)
        mins = int((end - submitted).total_seconds() / 60)
        elapsed = f"{mins // 60}h {mins % 60}m"
        print(f"{f['name']:<14}{f['status']:<12}{elapsed:<10}{f.get('faceId') or '-'}")

    ready = [f for f in state["faces"] if f["status"] == "ready"]
    if len(ready) > 1:
        # 동시 등록한 얼굴들의 완료 시각을 비교하면 병렬 처리 여부를 알 수 있다
        times = sorted(datetime.fromisoformat(f["readyAt"]) for f in ready)
        spread = int((times[-1] - times[0]).total_seconds() / 60)
        print(f"\n완료 시각 편차: {spread}분", end="  ")
        print("→ 병렬 처리로 보입니다" if spread < 60 else "→ 순차 처리 가능성. 유저 카드 영상통화 재검토 필요")


def cmd_watch(minutes=10):
    while True:
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}]")
        cmd_status()
        state = load_state()
        if all(f["status"] in ("ready", "failed") for f in state["faces"]):
            print("\n전부 끝났습니다.")
            return
        time.sleep(minutes * 60)


def cmd_faces():
    r = requests.get(f"{API}/faces", headers=headers(), timeout=30)
    r.raise_for_status()
    faces = r.json()
    print(f"등록된 얼굴 {len(faces)}개\n")
    for f in faces:
        print(f"  {f['id']}  v{f.get('simli_version')}  {f.get('created_at', '')[:19]}")


def cmd_sessions():
    r = requests.get(f"{API}/ratelimiter/sessions", headers=headers(), timeout=30)
    r.raise_for_status()
    print(f"현재 활성 세션: {r.json().get('currentUsage')}")


if __name__ == "__main__":
    cmds = {
        "register": lambda: cmd_register(sys.argv[2] if len(sys.argv) > 2 else HERE / "faces"),
        "status":   cmd_status,
        "watch":    lambda: cmd_watch(int(sys.argv[2]) if len(sys.argv) > 2 else 10),
        "faces":    cmd_faces,
        "sessions": cmd_sessions,
    }
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        sys.exit(__doc__)
    cmds[sys.argv[1]]()
