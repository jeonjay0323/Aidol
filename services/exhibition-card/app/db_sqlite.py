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
  owner_token  TEXT,                           -- 유저 카드 주인 (멀티콜 초대용)
  created_at   TEXT NOT NULL,
  ready_at     TEXT
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


def init():
    with connect() as con:
        con.executescript(SCHEMA)


def _row_to_dict(row):
    if row is None:
        return None
    d = dict(row)
    d["tags"] = json.loads(d["tags"])
    d["stats"] = json.loads(d["stats"])
    return d


def create_card(name, persona, voice="Puck", tags=None, stats=None,
                image_path=None, source="user", face_id=None, owner_token=None):
    card_id = new_card_id()
    face_status = "ready" if face_id else "none"
    with connect() as con:
        # 8자 랜덤이라 충돌은 사실상 없지만, 겹치면 다시 뽑는다
        while con.execute("SELECT 1 FROM cards WHERE card_id=?", (card_id,)).fetchone():
            card_id = new_card_id()
        con.execute(
            """INSERT INTO cards
               (card_id, name, persona, voice, tags, stats, image_path,
                source, face_id, face_status, owner_token, created_at, ready_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (card_id, name, persona, voice,
             json.dumps(tags or [], ensure_ascii=False),
             json.dumps(stats or {}, ensure_ascii=False),
             image_path, source, face_id, face_status,
             owner_token or secrets.token_urlsafe(16),
             now(), now() if face_id else None),
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


def pending_faces():
    """워커가 폴링해야 할 카드들."""
    return list_cards(face_status="processing")


if __name__ == "__main__":
    init()
    print(f"{DB} 준비 완료")
