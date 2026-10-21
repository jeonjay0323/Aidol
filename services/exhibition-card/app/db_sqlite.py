"""카드 저장소. 전시 규모에서는 SQLite로 충분하다."""
import json
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB = Path(__file__).parent.parent / "cards.db"

# 카드 발급은 즉시, 얼굴 등록은 최대 8시간.
# 그래서 card_id와 face_id를 분리하고 face_status로 그 간격을 표현한다.
SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
  card_id      TEXT PRIMARY KEY,
  name         TEXT NOT NULL,
  persona      TEXT NOT NULL,
  voice        TEXT NOT NULL DEFAULT 'Puck',
  tags         TEXT NOT NULL DEFAULT '[]',
  stats        TEXT NOT NULL DEFAULT '{}',
  image_path   TEXT,
  source       TEXT NOT NULL DEFAULT 'user',   -- official | user
  face_id      TEXT,
  face_status  TEXT NOT NULL DEFAULT 'none',   -- none | processing | ready | failed
  avatar_type  TEXT NOT NULL DEFAULT 'photo',  -- photo(Simli 실사) | vrm(버추얼 3D)
  model_path   TEXT,                           -- vrm 카드의 모델 파일
  custom       TEXT NOT NULL DEFAULT '{}',     -- 꾸미기 (색 · 말투 · 호칭)
  thumb_v      INTEGER,                        -- 꾸민 모습 스냅샷 버전 (thumbs 테이블)
  owner_token  TEXT,                           -- 유저 카드 주인 (멀티콜 초대용)
  created_at   TEXT NOT NULL,
  ready_at     TEXT
);
CREATE TABLE IF NOT EXISTS thumbs (
  card_id TEXT PRIMARY KEY,
  data    BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_face_status ON cards(face_status);
CREATE INDEX IF NOT EXISTS idx_source ON cards(source);
"""

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32 — 0/O, 1/I 혼동 제거


def now():
    return datetime.now(timezone.utc).isoformat()


def new_card_id():
    return "".join(secrets.choice(ALPHABET) for _ in range(8))


def connect():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


# 버추얼 카드 이전에 만들어진 DB에는 없는 컬럼들
MIGRATIONS = {
    "avatar_type": "TEXT NOT NULL DEFAULT 'photo'",
    "model_path": "TEXT",
    "custom": "TEXT NOT NULL DEFAULT '{}'",
    "thumb_v": "INTEGER",
}


def init():
    with connect() as con:
        con.executescript(SCHEMA)
        have = {r["name"] for r in con.execute("PRAGMA table_info(cards)")}
        for col, ddl in MIGRATIONS.items():
            if col not in have:
                con.execute(f"ALTER TABLE cards ADD COLUMN {col} {ddl}")


def _with_thumb(d):
    """꾸민 모습을 찍어둔 카드는 화면용 이미지를 그것으로 바꾼다.
    인쇄용 카드는 실물과 같아야 하므로 원래 이미지를 photo_path로 남긴다."""
    d["photo_path"] = d.get("image_path")
    if d.get("thumb_v"):
        d["image_path"] = f"/thumb/{d['card_id']}.jpg?v={d['thumb_v']}"
    return d


def _row_to_dict(row):
    if row is None:
        return None
    d = dict(row)
    d["tags"] = json.loads(d["tags"])
    d["stats"] = json.loads(d["stats"])
    d["custom"] = json.loads(d.get("custom") or "{}")
    return _with_thumb(d)


def create_card(name, persona, voice="Puck", tags=None, stats=None,
                image_path=None, source="user", face_id=None, owner_token=None,
                avatar_type="photo", model_path=None):
    card_id = new_card_id()
    # vrm 카드는 브라우저가 모델을 바로 그리므로 등록 대기가 없다
    ready = bool(face_id) or (avatar_type == "vrm" and bool(model_path))
    face_status = "ready" if ready else "none"
    with connect() as con:
        # 8자 랜덤이라 충돌은 사실상 없지만, 겹치면 다시 뽑는다
        while con.execute("SELECT 1 FROM cards WHERE card_id=?", (card_id,)).fetchone():
            card_id = new_card_id()
        con.execute(
            """INSERT INTO cards
               (card_id, name, persona, voice, tags, stats, image_path,
                source, face_id, face_status, avatar_type, model_path,
                owner_token, created_at, ready_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (card_id, name, persona, voice,
             json.dumps(tags or [], ensure_ascii=False),
             json.dumps(stats or {}, ensure_ascii=False),
             image_path, source, face_id, face_status, avatar_type, model_path,
             owner_token or secrets.token_urlsafe(16),
             now(), now() if ready else None),
        )
    return card_id


def get_card(card_id):
    with connect() as con:
        return _row_to_dict(
            con.execute("SELECT * FROM cards WHERE card_id=?", (card_id,)).fetchone()
        )


def list_cards(source=None, face_status=None):
    q, args = "SELECT * FROM cards", []
    where = []
    if source:
        where.append("source=?"); args.append(source)
    if face_status:
        where.append("face_status=?"); args.append(face_status)
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " ORDER BY created_at DESC"
    with connect() as con:
        return [_row_to_dict(r) for r in con.execute(q, args).fetchall()]


def set_face(card_id, face_id=None, face_status=None):
    sets, args = [], []
    if face_id is not None:
        sets.append("face_id=?"); args.append(face_id)
    if face_status is not None:
        sets.append("face_status=?"); args.append(face_status)
        if face_status == "ready":
            sets.append("ready_at=?"); args.append(now())
    if not sets:
        return
    args.append(card_id)
    with connect() as con:
        con.execute(f"UPDATE cards SET {', '.join(sets)} WHERE card_id=?", args)


def set_media(card_id, image_path=None, model_path=None):
    sets, args = [], []
    if image_path is not None:
        sets.append("image_path=?"); args.append(image_path)
    if model_path is not None:
        sets.append("model_path=?"); args.append(model_path)
    if not sets:
        return
    args.append(card_id)
    with connect() as con:
        con.execute(f"UPDATE cards SET {', '.join(sets)} WHERE card_id=?", args)


def set_custom(card_id, custom):
    with connect() as con:
        con.execute("UPDATE cards SET custom=? WHERE card_id=?",
                    (json.dumps(custom, ensure_ascii=False), card_id))


def set_thumb(card_id, data):
    import time
    with connect() as con:
        con.execute("INSERT OR REPLACE INTO thumbs (card_id, data) VALUES (?,?)", (card_id, data))
        con.execute("UPDATE cards SET thumb_v=? WHERE card_id=?", (int(time.time()), card_id))


def get_thumb(card_id):
    with connect() as con:
        row = con.execute("SELECT data FROM thumbs WHERE card_id=?", (card_id,)).fetchone()
    return row["data"] if row else None


def pending_faces():
    """워커가 폴링해야 할 카드들."""
    return list_cards(face_status="processing")


if __name__ == "__main__":
    init()
    print(f"{DB} 준비 완료")


# ── 이벤트 로그 ──────────────────────────────────────────
EVENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  type       TEXT NOT NULL,
  card_id    TEXT,
  session_id TEXT,
  meta       TEXT NOT NULL DEFAULT '{}',
  ts         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ev_type ON events(type);
CREATE INDEX IF NOT EXISTS idx_ev_card ON events(card_id);
"""


def log_event(type, card_id=None, session_id=None, meta=None):
    with connect() as con:
        con.executescript(EVENT_SCHEMA)
        con.execute(
            "INSERT INTO events (type, card_id, session_id, meta, ts) VALUES (?,?,?,?,?)",
            (type, card_id, session_id, json.dumps(meta or {}, ensure_ascii=False), now()),
        )
    return {"type": type, "card_id": card_id, "session_id": session_id, "ts": now()}


def list_events(limit=5000, type=None):
    with connect() as con:
        con.executescript(EVENT_SCHEMA)
        q = "SELECT * FROM events"
        args = []
        if type:
            q += " WHERE type=?"
            args.append(type)
        q += " ORDER BY ts ASC LIMIT ?"
        args.append(limit)
        rows = con.execute(q, args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["meta"] = json.loads(d["meta"])
        out.append(d)
    return out


def count_scans_by_card():
    with connect() as con:
        con.executescript(EVENT_SCHEMA)
        rows = con.execute(
            "SELECT card_id, COUNT(*) c FROM events WHERE type='scan' AND card_id IS NOT NULL GROUP BY card_id"
        ).fetchall()
    return {r["card_id"]: r["c"] for r in rows}
