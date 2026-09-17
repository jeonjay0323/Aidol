"""카드 저장소 — Firestore 백엔드.

db.py 와 같은 인터페이스를 제공한다. Cloud Run 은 컨테이너가 수시로 재시작되고
파일시스템이 휘발성이라 SQLite 파일을 쓸 수 없어서 이쪽을 쓴다.
맥에서 도는 얼굴 워커도 같은 Firestore 를 보므로 저장소가 하나로 합쳐진다.
"""
import os
import secrets
from datetime import datetime, timezone

from google.cloud import firestore

PROJECT = os.getenv("GCP_PROJECT", "aidol-505503")
COLLECTION = "cards"

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32 — 0/O, 1/I 혼동 제거

_client = None


def client():
    global _client
    if _client is None:
        _client = firestore.Client(project=PROJECT)
    return _client


def col():
    return client().collection(COLLECTION)


def now():
    return datetime.now(timezone.utc).isoformat()


def new_card_id():
    return "".join(secrets.choice(ALPHABET) for _ in range(8))


def init():
    """Firestore 는 스키마가 없어서 할 일이 없다. 연결만 확인한다."""
    client()


def _doc_to_dict(doc):
    if doc is None or not doc.exists:
        return None
    d = doc.to_dict()
    d["card_id"] = doc.id
    d.setdefault("tags", [])
    d.setdefault("stats", {})
    return d


def create_card(name, persona, voice="Puck", tags=None, stats=None,
                image_path=None, source="user", face_id=None, owner_token=None):
    card_id = new_card_id()
    while col().document(card_id).get().exists:
        card_id = new_card_id()

    col().document(card_id).set({
        "name": name,
        "persona": persona,
        "voice": voice,
        "tags": tags or [],
        "stats": stats or {},
        "image_path": image_path,
        "source": source,
        "face_id": face_id,
        "face_status": "ready" if face_id else "none",
        "owner_token": owner_token or secrets.token_urlsafe(16),
        "created_at": now(),
        "ready_at": now() if face_id else None,
    })
    return card_id


def get_card(card_id):
    return _doc_to_dict(col().document(card_id).get())


def list_cards(source=None, face_status=None):
    q = col()
    if source:
        q = q.where("source", "==", source)
    if face_status:
        q = q.where("face_status", "==", face_status)
    rows = [_doc_to_dict(d) for d in q.stream()]
    # created_at 정렬은 파이썬에서 한다 — 복합 인덱스를 만들지 않기 위해서.
    # 전시 규모(수십 장)에서는 비용 차이가 없다.
    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return rows


def set_face(card_id, face_id=None, face_status=None):
    patch = {}
    if face_id is not None:
        patch["face_id"] = face_id
    if face_status is not None:
        patch["face_status"] = face_status
        if face_status == "ready":
            patch["ready_at"] = now()
    if patch:
        col().document(card_id).update(patch)


def pending_faces():
    """워커가 폴링해야 할 카드들."""
    return list_cards(face_status="processing")


if __name__ == "__main__":
    init()
    print(f"Firestore 연결 확인 — {PROJECT}/{COLLECTION}, {len(list_cards())}장")


# ── 이벤트 로그 ──────────────────────────────────────────
# 소유감(카드 반출)과 애정(재방문)을 나눠 보려면 행동이 남아야 한다.
EVENTS = "events"


def _events():
    return client().collection(EVENTS)


def log_event(type, card_id=None, session_id=None, meta=None):
    doc = {
        "type": type, "card_id": card_id, "session_id": session_id,
        "meta": meta or {}, "ts": now(),
    }
    _events().add(doc)
    return doc


def list_events(limit=5000, type=None):
    q = _events()
    if type:
        q = q.where("type", "==", type)
    docs = q.limit(limit).stream()
    out = [d.to_dict() for d in docs]
    out.sort(key=lambda e: e.get("ts") or "")
    return out


def count_scans_by_card():
    """card_id -> 스캔 횟수. 2회 이상이면 재방문으로 본다."""
    counts = {}
    for e in list_events(type="scan"):
        cid = e.get("card_id")
        if cid:
            counts[cid] = counts.get(cid, 0) + 1
    return counts
