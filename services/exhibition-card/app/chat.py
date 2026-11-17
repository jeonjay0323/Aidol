"""
카드 아이돌과 글로 하는 채팅.

통화와 같은 페르소나(call.persona_of — 아이용 모드면 아이용 규칙 포함)를 쓰고,
대화 내용은 서버에 저장하지 않는다. 브라우저가 지난 대화를 들고 와서 매번 보낸다.
"""
import asyncio
import logging
import os
import random
import re
import time
import uuid

import google.genai as genai
from fastapi import APIRouter, HTTPException
from google.genai import types

from . import call, db

CHAT_MODEL = os.getenv("CHAT_MODEL", "gemini-2.5-flash")
MAX_TURNS = 20      # 브라우저가 보내는 지난 대화 중 최근 이만큼만 쓴다
MAX_CHARS = 300     # 한 번에 보낼 수 있는 글자 수

CHAT_RULES = """
[채팅 규칙]
지금은 전화가 아니라 문자 채팅이야. 메신저처럼 짧게 한두 문장으로만 답해. 줄을 바꾸지 말고 한 덩어리로 써.
한 번에 한 사람에게만 말해. 이모지는 가끔 하나 정도만. 목록이나 긴 설명은 쓰지 마.
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
LISTEN_TURNS = 4    # '둘이 얘기해 봐' 하면 아이돌끼리 이만큼 주고받는다

# "둘이 얘기해 봐", "너희끼리 대화해", "난 듣고만 있을게" 같은 말
_LISTEN = re.compile(r"(둘이|셋이|넷이|너희|니네|서로|끼리).{0,8}(얘기|이야기|대화|말|수다)|듣고만|듣기만|구경만|talk to each other", re.I)


def wants_listen(text):
    return bool(_LISTEN.search(text or ""))


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
            role, text = "user", f"{m.get('by') or '나'}: {m['text']}"
        if out and out[-1][0] == role:
            out[-1][1].append(text)
        else:
            out.append((role, [text]))
    return [types.Content(role=r, parts=[types.Part(text="\n".join(t))]) for r, t in out]


async def _reply(card, msgs, members, names, listen=False, people=(), extra_speakers=()):
    group = len(members) > 1
    system = call.persona_of(card) + "\n\n" + CHAT_RULES
    if group:
        others = ", ".join(names[c] for c in members if c != card["card_id"])
        humans = ", ".join(people) if people else "상대('나')"
        system += (f"\n\n[단체 채팅방] 지금 너({card['name']}), 사람 친구({humans}), 그리고 {others}가 함께 있는 단체 채팅방이야. "
                   "다른 사람 말 앞에는 '이름: '이 붙어 있어. 네 답 앞에는 이름을 붙이지 마. "
                   "다른 아이돌의 말에 자연스럽게 반응하거나 말을 걸어도 돼. 그래도 대화의 주인공은 '나'야. "
                   "너 자신의 말만 써. 다른 사람의 대사를 대신 쓰지 마.")
        if listen:
            system += ("\n\n[지금은 사람 친구들이 듣고 있어] 다른 아이돌과 대화를 이어가. "
                       "방금 말한 아이돌에게 직접 대답하고, 이어서 그 아이돌에게 질문하거나 새 이야기를 꺼내. "
                       "사람 친구에게 질문하지 마. 앞에서 한 말을 되풀이하지 마.")
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
    speakers = ["나"] + [n for n in names.values() if n != card["name"]] + list(extra_speakers)
    kept = []
    for i, line in enumerate(text.splitlines()):
        head = next((sp for sp in speakers if line.strip().startswith(sp + ":")), None)
        if head and i == 0:
            line = line.strip()[len(head) + 1:].strip()
        elif head:
            break
        kept.append(line)
    # 문단을 하나로 합치고, 너무 길면 세 문장까지만
    text = " ".join(l.strip() for l in kept if l.strip())
    parts = re.split(r"(?<=[.!?。！？~])\s+", text)
    if len(parts) > 3:
        text = " ".join(parts[:3])
    if not text:
        log.info(f"빈 답: {card['name']} / {(r.text or '')[:80]!r}")
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
    cont = bool(payload.get("continue"))      # '계속 듣기' — 새 메시지 없이 아이돌끼리 이어간다
    if not msgs or (msgs[-1]["role"] != "user" and not cont):
        raise HTTPException(400, "보낼 메시지가 없어요")
    listen = len(members) > 1 and (cont or bool(payload.get("listen")) or wants_listen(msgs[-1]["text"]))

    # 누가 답할까 — 이름이 불렸으면 그 아이돌, 아니면 가장 오래 말을 안 한 아이돌
    last_said = {cid: -1 for cid in members}
    for i, m in enumerate(msgs):
        if m["role"] == "model" and m["who"] in last_said:
            last_said[m["who"]] = i
    last_who = msgs[-1].get("who") if msgs[-1]["role"] == "model" else None
    called = [cid for cid in members if msgs[-1]["role"] == "user" and names[cid] in msgs[-1]["text"]]
    pool = [c for c in members if c != last_who] or members
    first = called[0] if called else min(pool, key=lambda c: last_said[c])
    order = [first]
    turns = LISTEN_TURNS if listen else (2 if len(members) > 1 else 1)
    while len(order) < turns:
        # 방금 말한 아이돌은 빼고, 가장 오래 말을 안 한 아이돌이 받는다
        seen = dict(last_said)
        for i, c in enumerate(order):
            seen[c] = len(msgs) + i
        rest = [c for c in members if c != order[-1]]
        order.append(min(rest, key=lambda c: seen[c]))

    replies = []
    try:
        for cid in order:
            text = await _reply(cards[cid], msgs, members, names, listen=listen)
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
    return {"reply": replies[0]["text"], "replies": replies, "listen": listen}


# ───────── 채팅방 ─────────
# 친구가 방 번호로 들어와 같은 방에서 이야기한다. 방은 서버 메모리에만 있고(저장하지 않음) 2시간 뒤 사라진다.
# 같은 방을 여러 인스턴스가 나눠 갖지 않도록 이 서비스는 인스턴스 1개로 돌린다(배포 --max-instances 1).
ROOMS = {}
_TASKS = set()   # 백그라운드 답 작업이 중간에 사라지지 않게 잡아 둔다


def _bg(coro):
    t = asyncio.create_task(coro)
    _TASKS.add(t)
    t.add_done_callback(_TASKS.discard)
ROOM_TTL = 2 * 3600
AUTO_IDLE = 3.5        # 마지막 말 뒤 이만큼 조용하면 아이돌끼리 이어서 말한다(아이돌 2명 이상일 때)
AUTO_MAX = 8           # 사람이 말하지 않는 동안 아이돌끼리 이어가는 최대 횟수
AUTO_MAX_LISTEN = 14   # '둘이 얘기해 봐' 했을 때
MAX_PEOPLE = 4


def _gc():
    now = time.time()
    for code in [c for c, r in ROOMS.items() if now - r["touched"] > ROOM_TTL]:
        ROOMS.pop(code, None)


def _room(code):
    r = ROOMS.get(str(code))
    if not r:
        raise HTTPException(404, "그 번호의 채팅방이 없어요")
    r["touched"] = time.time()
    return r


def _add_idol(r, card):
    if card["card_id"] in r["cards"] or len(r["cards"]) >= MAX_MEMBERS:
        return False
    r["cards"][card["card_id"]] = card
    return True


def _post(r, **m):
    m["id"] = r["seq"] = r["seq"] + 1
    m["at"] = time.time()
    r["msgs"].append(m)
    r["msgs"] = r["msgs"][-200:]
    return m


def _greet(r, card, joined_by=None):
    n = card["name"]
    c = ord(n[-1]) - 0xAC00
    ya = "이야" if 0 <= c < 11172 and c % 28 else "야"
    _post(r, role="note", text=f"{n}{'이' if ya == '이야' else '가'} 들어왔어요" + (f" ({joined_by})" if joined_by else ""))
    _post(r, role="model", who=card["card_id"], text=f"안녕! 나 {n}{ya}. " + ("오늘 어땠어?" if len(r["cards"]) == 1 else "나도 같이 얘기해도 돼?"))


def _view(r, since=0):
    return {
        "code": r["code"],
        "members": [{"cardId": c["card_id"], "name": c["name"], "image": c.get("image_path")} for c in r["cards"].values()],
        "people": list(r["people"].values()),
        "msgs": [{k: m.get(k) for k in ("id", "role", "who", "by", "pid", "text")} for m in r["msgs"] if m["id"] > since],
        "busy": r["busy"],
    }


async def _speak(r, turns, listen):
    """방 안의 아이돌이 turns 번 말한다. 한 번에 하나씩만 돈다."""
    if r["busy"]:
        return
    r["busy"] = True
    try:
        cards = r["cards"]
        members = list(cards)
        names = {cid: c["name"] for cid, c in cards.items()}
        people = list(r["people"].values())
        for _ in range(turns):
            msgs = [m for m in r["msgs"] if m["role"] in ("user", "model")][-MAX_TURNS:]
            if not msgs:
                return
            last = msgs[-1]
            said = {cid: -1 for cid in members}
            for i, m in enumerate(msgs):
                if m["role"] == "model" and m.get("who") in said:
                    said[m["who"]] = i
            called = [c for c in members if last["role"] == "user" and names[c] in last["text"]]
            pool = [c for c in members if c != last.get("who")] or members
            cid = called[0] if called else min(pool, key=lambda c: (said[c], random.random()))
            text = await _reply(cards[cid], msgs, members, names, listen=listen and last["role"] == "model",
                                people=people, extra_speakers=people)
            if text:
                _post(r, role="model", who=cid, text=text)
    except Exception as e:
        log.warning(f"채팅방 답 실패: {e}")
    finally:
        r["busy"] = False


@router.post("/api/chat/rooms")
async def room_open(payload: dict):
    """내 카드로 채팅방을 연다."""
    _gc()
    card = db.get_card(str(payload.get("cardId") or ""))
    if not card:
        raise HTTPException(404, "카드를 찾을 수 없습니다")
    code = next(c for c in (f"{random.randint(1000, 9999)}" for _ in range(50)) if c not in ROOMS)
    pid = str(payload.get("pid") or uuid.uuid4().hex[:10])[:16]
    r = ROOMS[code] = {"code": code, "cards": {}, "people": {}, "msgs": [], "seq": 0, "busy": False,
                       "touched": time.time(), "last_human": time.time(), "auto_left": 0, "listen": False}
    r["people"][pid] = f"{card['name']} 친구"
    _add_idol(r, card)
    _greet(r, card)
    try:
        db.log_event("chat_room", card_id=card["card_id"], meta={"act": "open"})
    except Exception:
        pass
    return {"pid": pid, **_view(r)}


@router.post("/api/chat/rooms/{code}/join")
async def room_join(code: str, payload: dict):
    """친구가 방 번호로 들어온다 — 친구의 아이돌도 함께."""
    r = _room(code)
    card = db.get_card(str(payload.get("cardId") or ""))
    if not card:
        raise HTTPException(404, "카드를 찾을 수 없습니다")
    pid = str(payload.get("pid") or uuid.uuid4().hex[:10])[:16]
    if pid not in r["people"]:
        if len(r["people"]) >= MAX_PEOPLE:
            raise HTTPException(409, "방이 꽉 찼어요")
        r["people"][pid] = f"{card['name']} 친구"
        if not _add_idol(r, card):
            _post(r, role="note", text=f"{card['name']} 친구가 들어왔어요")
        else:
            _greet(r, card, joined_by="친구와 함께")
    try:
        db.log_event("chat_room", card_id=card["card_id"], meta={"act": "join", "size": len(r["people"])})
    except Exception:
        pass
    return {"pid": pid, **_view(r)}


@router.post("/api/chat/rooms/{code}/invite")
async def room_invite(code: str, payload: dict):
    """아이돌만 부른다(공식 아이돌 · 친구 아이돌)."""
    r = _room(code)
    card = db.get_card(str(payload.get("cardId") or "").upper())
    if not card:
        raise HTTPException(404, "그 번호의 카드가 없어요")
    if len(r["cards"]) >= MAX_MEMBERS:
        raise HTTPException(409, f"아이돌은 {MAX_MEMBERS}명까지 들어올 수 있어요")
    if _add_idol(r, card):
        _greet(r, card)
    return _view(r, int(payload.get("since") or 0))


@router.post("/api/chat/rooms/{code}/say")
async def room_say(code: str, payload: dict):
    r = _room(code)
    text = str(payload.get("text") or "").strip()[:MAX_CHARS]
    pid = str(payload.get("pid") or "")
    if not text or pid not in r["people"]:
        raise HTTPException(400, "보낼 메시지가 없어요")
    _post(r, role="user", by=r["people"][pid], pid=pid, text=text)
    r["last_human"] = time.time()
    r["listen"] = wants_listen(text)
    r["auto_left"] = AUTO_MAX_LISTEN if r["listen"] else AUTO_MAX
    try:
        db.log_event("chat", card_id=next(iter(r["cards"])), meta={"room": True, "members": len(r["cards"]), "people": len(r["people"])})
    except Exception:
        pass
    # 사람 말에는 한 명이 바로 답하고, 아이돌이 둘 이상이면 한 명이 받아친다
    _bg(_speak(r, 2 if len(r["cards"]) > 1 else 1, listen=False))
    return _view(r, int(payload.get("since") or 0))


@router.get("/api/chat/rooms/{code}")
async def room_poll(code: str, since: int = 0):
    """새 메시지를 받아 간다. 조용하면 아이돌끼리 이어서 말하게 한다."""
    r = _room(code)
    msgs = r["msgs"]
    if (len(r["cards"]) > 1 and not r["busy"] and r["auto_left"] > 0 and msgs
            and msgs[-1]["role"] == "model" and time.time() - msgs[-1]["at"] > AUTO_IDLE):
        r["auto_left"] -= 1
        _bg(_speak(r, 1, listen=True))
    return _view(r, since)
