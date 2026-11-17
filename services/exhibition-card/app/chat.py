"""
카드 아이돌과 글로 하는 채팅.

통화와 같은 페르소나(call.persona_of — 아이용 모드면 아이용 규칙 포함)를 쓰고,
대화 내용은 서버에 저장하지 않는다. 브라우저가 지난 대화를 들고 와서 매번 보낸다.
"""
import logging
import os

import google.genai as genai
from fastapi import APIRouter, HTTPException
from google.genai import types

from . import call, db

CHAT_MODEL = os.getenv("CHAT_MODEL", "gemini-2.5-flash")
MAX_TURNS = 20      # 브라우저가 보내는 지난 대화 중 최근 이만큼만 쓴다
MAX_CHARS = 300     # 한 번에 보낼 수 있는 글자 수

CHAT_RULES = """
[채팅 규칙]
지금은 전화가 아니라 문자 채팅이야. 메신저처럼 짧게 한두 문장으로 답해.
이모지는 가끔 하나 정도만. 목록이나 긴 설명은 쓰지 마.
""".strip()

log = logging.getLogger("chat")
router = APIRouter()
_client = None


def client():
    global _client
    if _client is None:
        _client = genai.Client(vertexai=True, project=call.GCP_PROJECT, location=call.GCP_LOCATION)
    return _client


@router.post("/api/cards/{card_id}/chat")
async def chat(card_id: str, payload: dict):
    card = db.get_card(card_id)
    if not card:
        raise HTTPException(404, "카드를 찾을 수 없습니다")

    history = []
    for m in (payload.get("messages") or [])[-MAX_TURNS:]:
        text = str(m.get("text") or "").strip()[:MAX_CHARS]
        if not text:
            continue
        role = "model" if m.get("role") == "model" else "user"
        history.append(types.Content(role=role, parts=[types.Part(text=text)]))
    if not history or history[-1].role != "user":
        raise HTTPException(400, "보낼 메시지가 없어요")

    try:
        r = await client().aio.models.generate_content(
            model=CHAT_MODEL,
            contents=history,
            config=types.GenerateContentConfig(
                system_instruction=call.persona_of(card) + "\n\n" + CHAT_RULES,
                max_output_tokens=300,
                temperature=0.9,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        reply = (r.text or "").strip()
    except Exception as e:
        log.warning(f"채팅 실패: {e}")
        raise HTTPException(502, "지금은 답장을 못 했어요. 잠시 뒤 다시 보내 주세요.")
    if not reply:
        reply = "음… 그 얘기는 잘 모르겠어. 다른 얘기 해 볼까?"

    try:
        # 내용은 남기지 않는다 — 몇 번째 메시지인지만
        db.log_event("chat", card_id=card_id, meta={"turn": len(history)})
    except Exception as e:
        log.warning(f"chat 로그 실패: {e}")
    return {"reply": reply}
