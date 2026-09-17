"""카드 저장소 진입점.

DB_BACKEND=firestore 면 Firestore, 아니면 로컬 SQLite 를 쓴다.
Cloud Run 은 파일시스템이 휘발성이라 Firestore 가 필요하고,
맥에서 개발할 때는 SQLite 가 편해서 둘 다 남겨둔다.
"""
import os

if os.getenv("DB_BACKEND", "sqlite").lower() == "firestore":
    from .db_firestore import (  # noqa: F401
        ALPHABET, create_card, get_card, init, list_cards,
        new_card_id, now, pending_faces, set_face,
        log_event, list_events, count_scans_by_card,
    )
else:
    from .db_sqlite import (  # noqa: F401
        ALPHABET, create_card, get_card, init, list_cards,
        new_card_id, now, pending_faces, set_face,
        log_event, list_events, count_scans_by_card,
    )
