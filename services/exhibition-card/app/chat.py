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


MAX_MEMBERS = 4     # 한 채팅방의 아이돌 수 (처음 카드 포함)


def _contents_for(me_id, msgs, names):
    """한 아이돌 입장의 대화. 자기 말은 model, 사람과 다른 아이돌 말은 '이름: 말' 로 user 쪽에 둔다.
    같은 쪽이 이어지면 한 덩어리로 합친다."""
    out = []
    for m in msgs:
        if m["role"] == "model" and m.get("who") == me_id:
            role, text = "model", m["text"]
        elif m["role"] == "model":
            role, text = "user", f"{names.get(m.get('who'), '친구')}: {m['text']}"
        else:
            role, text = "user", f"나: {m['text']}"
        if out and out[-1][0] == role:
            out[-1][1].append(text)
        else:
            out.append((role, [text]))
    return [types.Content(role=r, parts=[types.Part(text="\n".join(t))]) for r, t in out]


async def _reply(card, msgs, members, names):
    group = len(members) > 1
    system = call.persona_of(card) + "\n\n" + CHAT_RULES
    if group:
        others = ", ".join(names[c] for c in members if c != card["card_id"])
        system += (f"\n\n[단체 채팅방] 지금 너({card['name']}), 상대('나'), 그리고 {others}가 함께 있는 단체 채팅방이야. "
                   "다른 사람 말 앞에는 '이름: '이 붙어 있어. 네 답 앞에는 이름을 붙이지 마. "
                   "다른 아이돌의 말에 자연스럽게 반응하거나 말을 걸어도 돼. 그래도 대화의 주인공은 '나'야. "
                   "너 자신의 말만 써. 다른 사람의 대사를 대신 쓰지 마.")
    contents = _contents_for(card["card_id"], msgs, names)
    if not contents or contents[-1].role != "user":
        return None
    r = await client().aio.models.generate_content(
        model=CHAT_MODEL, contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system, max_output_tokens=300, temperature=0.9,
            thinking_config=types.ThinkingConfig(thinking_budget=0)),
    )
    text = (r.text or "").strip()
    prefix = card["name"] + ":"
    if text.startswith(prefix):
        text = text[len(prefix):].strip()
    # 다른 사람 대사('나: …', '시온: …')까지 지어내면 거기서 자른다
    speakers = ["나"] + [n for n in names.values() if n != card["name"]]
    kept = []
    for line in text.splitlines():
        if any(line.strip().startswith(sp + ":") for sp in speakers):
            break
        kept.append(line)
    text = "\n".join(kept).strip()
    return text or None


@router.post("/api/cards/{card_id}/chat")
async def chat(card_id: str, payload: dict):
    """1:1 이면 처음 카드가 답한다. 다른 아이돌을 초대했으면(members) 이름이 불린 아이돌이 먼저,
    아니면 돌아가며 한 명이 답하고, 다른 한 명이 한 번 받아친다."""
    host = db.get_card(card_id)
    if not host:
        raise HTTPException(404, "카드를 찾을 수 없습니다")
    ids = [card_id] + [c for c in (payload.get("members") or []) if isinstance(c, str) and c != card_id]
    cards = {}
    for cid in dict.fromkeys(ids[:MAX_MEMBERS]):
        c = host if cid == card_id else db.get_card(cid)
        if c:
            cards[cid] = c
    members = list(cards)
    names = {cid: c["name"] for cid, c in cards.items()}

    msgs = []
    for m in (payload.get("messages") or [])[-MAX_TURNS:]:
        text = str(m.get("text") or "").strip()[:MAX_CHARS]
        if not text:
            continue
        role = "model" if m.get("role") == "model" else "user"
        msgs.append({"role": role, "text": text, "who": m.get("who") or card_id if role == "model" else None})
    if not msgs or msgs[-1]["role"] != "user":
        raise HTTPException(400, "보낼 메시지가 없어요")

    # 누가 답할까 — 이름이 불렸으면 그 아이돌, 아니면 가장 오래 말을 안 한 아이돌
    last_said = {cid: -1 for cid in members}
    for i, m in enumerate(msgs):
        if m["role"] == "model" and m["who"] in last_said:
            last_said[m["who"]] = i
    called = [cid for cid in members if names[cid] in msgs[-1]["text"]]
    first = called[0] if called else min(members, key=lambda c: last_said[c])
    order = [first]
    if len(members) > 1:
        rest = [c for c in members if c != first]
        order.append(min(rest, key=lambda c: last_said[c]))

    replies = []
    try:
        for cid in order:
            text = await _reply(cards[cid], msgs, members, names)
            if not text:
                continue
            msgs.append({"role": "model", "text": text, "who": cid})
            replies.append({"cardId": cid, "name": names[cid], "text": text})
    except Exception as e:
        log.warning(f"채팅 실패: {e}")
        if not replies:
            raise HTTPException(502, "지금은 답장을 못 했어요. 잠시 뒤 다시 보내 주세요.")
    if not replies:
        replies = [{"cardId": card_id, "name": names[card_id], "text": "음… 그 얘기는 잘 모르겠어. 다른 얘기 해 볼까?"}]

    try:
        # 내용은 남기지 않는다 — 몇 번째 메시지인지, 몇 명이 있는지만
        db.log_event("chat", card_id=card_id, meta={"turn": len(msgs), "members": len(members)})
    except Exception as e:
        log.warning(f"chat 로그 실패: {e}")
    return {"reply": replies[0]["text"], "replies": replies}
