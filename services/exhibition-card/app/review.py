"""
후기 — 사용자가 남긴 별점과 한 줄 후기를 기록하고 운영자에게 메일로 보낸다.

메일은 Gmail SMTP(앱 비밀번호)로 보낸다. 아래 환경변수가 없으면 기록만 하고 메일은 건너뛴다.
  REVIEW_TO   받는 주소
  SMTP_USER   보내는 Gmail 주소
  SMTP_PASS   그 계정의 앱 비밀번호 (Google 계정 → 보안 → 2단계 인증 → 앱 비밀번호)
"""
import asyncio
import logging
import os
import smtplib
from email.message import EmailMessage

from fastapi import APIRouter, HTTPException

from . import db

log = logging.getLogger("review")
router = APIRouter()


def _send(subject, body):
    to, user, pw = os.getenv("REVIEW_TO"), os.getenv("SMTP_USER"), os.getenv("SMTP_PASS")
    if not (to and user and pw):
        log.info("메일 설정이 없어 후기 메일은 건너뜀")
        return False
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.set_content(body)
    with smtplib.SMTP_SSL(os.getenv("SMTP_HOST", "smtp.gmail.com"), int(os.getenv("SMTP_PORT", "465")), timeout=15) as s:
        s.login(user, pw)
        s.send_message(msg)
    return True


@router.post("/api/review")
async def review(payload: dict):
    text = str(payload.get("text") or "").strip()[:1000]
    try:
        stars = int(payload.get("stars") or 0)
        stars = min(5, stars) if stars > 0 else 0   # 별점 없이 글만 남겨도 된다
    except (TypeError, ValueError):
        stars = 0
    if not text and not stars:
        raise HTTPException(400, "별점이나 후기를 남겨 주세요")
    card_id = str(payload.get("cardId") or "")[:16] or None
    who = str(payload.get("name") or "").strip()[:20]
    feature = str(payload.get("feature") or "").strip()[:20]
    page = str(payload.get("page") or "").strip()[:60]
    card = db.get_card(card_id) if card_id else None

    try:
        db.log_event("review", card_id=card_id, meta={"stars": stars, "text": text, "name": who,
                                                       "feature": feature, "page": page})
    except Exception as e:
        log.warning(f"review 로그 실패: {e}")

    idol = card["name"] if card else "—"
    body = (f"별점: {'★' * stars}{'☆' * (5 - stars)} ({stars}/5)\n"
            f"기능: {feature or '—'} ({page or '—'})\n"
            f"아이돌: {idol} ({card_id or '—'})\n"
            f"남긴 사람: {who or '익명'}\n\n{text or '(후기 없음)'}\n")
    try:
        sent = await asyncio.to_thread(_send, f"[LUKIDS 후기] {feature or idol} · {stars}점", body)
    except Exception as e:
        log.warning(f"후기 메일 실패: {e}")
        sent = False
    return {"ok": True, "mailed": sent}
