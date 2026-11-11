"""
멀티콜 — 발언권 중재 방식.

한 방에 아이돌 여러 명이 들어오지만 동시에 말하면 겹치므로, 서버가 매 턴
'지금 답할 사람' 하나를 정한다. 사람의 음성은 그 한 명에게만 실시간으로 흐르고,
나머지에게는 오간 말을 텍스트로 넣어 맥락만 따라가게 한다.
그래서 다음 차례가 와도 대화를 알고 있다.
"""
import asyncio
import time
import base64
import json
import logging
import os
from pathlib import Path

import google.genai as genai
from dotenv import load_dotenv
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from google.genai import types

from . import call, db

load_dotenv(Path(__file__).parent.parent / ".env")
GCP_PROJECT = os.getenv("GCP_PROJECT", "project-d4a769de-d13f-4a6a-a22")
GCP_LOCATION = os.getenv("GCP_LOCATION", "us-central1")
LIVE_MODEL = os.getenv("LIVE_MODEL", "gemini-live-2.5-flash-native-audio")

log = logging.getLogger("room")

# 사람 발화 한 번당 아이돌끼리 주고받을 최대 횟수 — 2 는 둘이 너무 오래 떠들어서 1 로 (2026-10-07)
MAX_RELAYS = 1
MAX_RECONNECT = 3   # 한 멤버의 Gemini 재연결을 이만큼 연달아 실패하면 통화를 끝낸다
router = APIRouter()


def build_config(card, others, handle=None):
    """다른 멤버가 누구인지 알려줘야 서로를 아는 대화가 된다."""
    persona = call.persona_of(card)
    if others:
        names = ", ".join(o["name"] for o in others)
        persona += (
            f"\n\n지금 {names}와(과) 함께 단체 영상통화 중이야. "
            f"상대가 한 말은 '(이름): 내용' 형태로 전달돼. "
            f"네 차례에만 말하고, 다른 사람 말에 자연스럽게 반응해. "
            f"이름을 부르며 대화해도 좋아. 한 번에 딱 한 문장, 아주 짧게 말하고 "
            f"사람(통화를 건 친구)에게 말을 넘겨."
        )
    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=persona,
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=card["voice"])
            )
        ),
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(disabled=True)
        ),
        # 오간 말을 텍스트로 받아 다른 멤버에게 넘긴다
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        # Gemini 세션은 약 10분이면 서버가 끊는다. 대화 내용을 이어받아 통화는 유지한다
        session_resumption=types.SessionResumptionConfig(handle=handle),
        context_window_compression=types.ContextWindowCompressionConfig(
            sliding_window=types.SlidingWindow()
        ),
    )


class Room:
    def __init__(self, websocket, cards, room_id=""):
        self.ws = websocket
        self.cards = cards
        self.room_id = room_id
        self.sessions = {}          # card_id -> live session. 갈아타는 동안에는 None
        self.handles = {}           # card_id -> 이어받기 토큰
        self.user_active = False    # 사람이 말하는 중
        self.open_activity = set()  # activity_start 를 보낸 세션의 card_id
        self.client_gone = asyncio.Event()
        self.turn = 0               # 라운드로빈 커서
        self.target = None          # 클라이언트가 지목한 상대
        self.speaking = None        # 이번 턴 화자
        self.relay_turn = 0         # 아이돌끼리 이어 말할 때의 커서
        self.relays = 0             # 사람 발화 이후 연속 릴레이 횟수
        self.lock = asyncio.Lock()

    def pick_speaker(self):
        """지목이 있으면 그 사람, 없으면 돌아가며."""
        if self.target and self.sessions.get(self.target):
            return self.target
        cid = self.cards[self.turn % len(self.cards)]["card_id"]
        self.turn += 1
        return cid

    async def inject(self, text, speaker_name, exclude):
        """오간 말을 나머지 멤버의 맥락에 텍스트로 넣는다 (응답은 유발하지 않음)."""
        for cid, sess in self.sessions.items():
            if cid == exclude or sess is None:
                continue
            try:
                await sess.send_client_content(
                    turns=types.Content(role="user",
                                        parts=[types.Part(text=f"({speaker_name}): {text}")]),
                    turn_complete=False,
                )
            except Exception as e:
                log.warning(f"맥락 주입 실패 {cid}: {e}")

    async def relay(self, from_cid, from_name, text):
        """한 아이돌이 말하면 다른 아이돌이 받아치게 한다.
        사람이 말할 때까지 무한히 주고받지 않도록 연속 횟수를 제한한다."""
        if self.relays >= MAX_RELAYS or len(self.cards) < 2:
            return
        others = [c for c in self.cards if c["card_id"] != from_cid]
        nxt = others[self.relay_turn % len(others)]
        sess = self.sessions.get(nxt["card_id"])
        if sess is None:
            return   # 그 멤버가 세션을 갈아타는 중이면 이번 받아치기는 건너뛴다
        self.relay_turn += 1
        self.relays += 1
        log.info(f"릴레이 {self.relays}/{MAX_RELAYS}: {from_name} → {nxt['name']}")
        await self.ws.send_text(json.dumps({"type": "turn_start", "cardId": nxt["card_id"]}))
        try:
            await sess.send_client_content(
                turns=types.Content(role="user",
                                    parts=[types.Part(text=f"({from_name}): {text}")]),
                turn_complete=True,   # 이번엔 응답을 유발한다
            )
        except Exception as e:
            log.warning(f"릴레이 실패 {nxt['card_id']}: {e}")

    async def member(self, card, others, client, ready):
        """한 멤버의 Gemini 세션을 유지한다. 끊기면 대화를 이어받아 다시 연다."""
        cid = card["card_id"]
        failures = 0
        while not self.client_gone.is_set():
            try:
                async with client.aio.live.connect(
                    model=LIVE_MODEL, config=build_config(card, others, self.handles.get(cid))
                ) as sess:
                    failures = 0
                    self.open_activity.discard(cid)
                    if self.user_active and self.speaking == cid:
                        await sess.send_realtime_input(activity_start=types.ActivityStart())
                        self.open_activity.add(cid)
                    self.sessions[cid] = sess
                    if ready.done():
                        log.info(f"Gemini 세션 이어받음: {card['name']}")
                    else:
                        ready.set_result(True)
                    pump = asyncio.create_task(self.pump(card, sess))
                    gone = asyncio.create_task(self.client_gone.wait())
                    try:
                        await asyncio.wait({pump, gone}, return_when=asyncio.FIRST_COMPLETED)
                    finally:
                        self.sessions[cid] = None
                        pump.cancel()
                        gone.cancel()
                        await asyncio.gather(pump, gone, return_exceptions=True)
            except Exception as e:
                if not ready.done():
                    ready.set_exception(e)
                    return
                if self.client_gone.is_set():
                    return
                failures += 1
                log.warning(f"Gemini 재연결 실패 {card['name']} {failures}/{MAX_RECONNECT}: {e}")
                if failures >= MAX_RECONNECT:
                    try:
                        await self.ws.send_text(json.dumps({"type": "error", "data": str(e)}))
                    except Exception:
                        pass
                    self.client_gone.set()
                    return
                await asyncio.sleep(failures)

    async def pump(self, card, sess):
        """한 멤버의 응답을 받아 클라이언트로 넘기고, 나머지에게 텍스트로 공유한다.
        세션이 끝나면 돌아오고, member() 가 이어받아 다시 연다."""
        cid, name = card["card_id"], card["name"]
        leaving = False
        said = []
        started, nbytes = None, 0   # 이번 턴 오디오 — 재생이 끝나는 시각을 어림한다
        try:
            while True:
                async for response in sess.receive():
                    update = getattr(response, "session_resumption_update", None)
                    if update and update.resumable and update.new_handle:
                        self.handles[cid] = update.new_handle
                    if getattr(response, "go_away", None):
                        log.info(f"Gemini 세션 만료 예고: {name}")
                        leaving = True
                    # 말이 오가지 않는 틈에 갈아타야 끊김이 들리지 않는다
                    if leaving and started is None and not (self.user_active and self.speaking == cid):
                        return
                    if response.data:
                        if started is None:
                            started = time.monotonic()
                        nbytes += len(response.data)
                        await self.ws.send_text(json.dumps({
                            "type": "audio", "cardId": cid,
                            "data": base64.b64encode(response.data).decode(),
                        }))
                    sc = getattr(response, "server_content", None)
                    if not sc:
                        continue
                    out = getattr(sc, "output_transcription", None)
                    if out and getattr(out, "text", None):
                        said.append(out.text)
                        # 자막은 조각째 바로 보낸다 — 브라우저가 그 소리가 재생되는 순간에 띄운다
                        await self.ws.send_text(json.dumps({"type": "text", "cardId": cid, "text": out.text}))
                    if getattr(sc, "turn_complete", False):
                        text = "".join(said).strip()
                        said = []
                        await self.ws.send_text(json.dumps({
                            "type": "turn_complete", "cardId": cid, "text": text,
                        }))
                        if text:
                            log.info(f"{name}: {text}")
                            await self.inject(text, name, exclude=cid)
                            # 생성은 재생보다 빠르다. 다음 사람은 이 말이 다 들린 뒤에 시작해야 겹치지 않는다
                            if started is not None:
                                left = started + nbytes / 48000 - time.monotonic()   # 24kHz · 16bit
                                if left > 0:
                                    await asyncio.sleep(left + 0.4)
                            # 맥락만 넣으면 대화가 거기서 끊긴다. 한 명은 받아치게 한다.
                            await self.relay(cid, name, text)
                        started, nbytes = None, 0
                        break
        except Exception as e:
            log.info(f"pump 종료 {cid}: {e}")
            # 말하던 중에 끊겼으면 그 턴은 닫아 준다
            if started is not None:
                try:
                    await self.ws.send_text(json.dumps(
                        {"type": "turn_complete", "cardId": cid, "text": ""}))
                except Exception:
                    pass

    async def from_client(self):
        try:
            while True:
                msg = json.loads(await self.ws.receive_text())
                t = msg.get("type")

                if t == "target":
                    self.target = msg.get("cardId")
                    # 누구를 지목했는지가 RQ2(통제 욕구·자기 것 편애)의 핵심 지표다
                    try:
                        db.log_event("room_target", card_id=self.target,
                                     session_id=self.room_id,
                                     meta={"host": self.cards[0]["card_id"]})
                    except Exception as e:
                        log.warning(f"room_target 로그 실패: {e}")

                elif t == "activity_start":
                    async with self.lock:
                        self.relays = 0          # 사람이 끼어들면 릴레이를 새로 센다
                        self.speaking = self.pick_speaker()
                        self.user_active = True
                    await self.ws.send_text(json.dumps(
                        {"type": "turn_start", "cardId": self.speaking}))
                    sess = self.sessions.get(self.speaking)
                    if sess:
                        await self.send_safely(sess, activity_start=types.ActivityStart())
                        self.open_activity.add(self.speaking)

                elif t == "audio" and self.speaking:
                    sess = self.sessions.get(self.speaking)
                    if sess:
                        await self.send_safely(sess, audio=types.Blob(
                            data=base64.b64decode(msg["data"]),
                            mime_type="audio/pcm;rate=16000"))

                elif t == "activity_end" and self.speaking:
                    self.user_active = False
                    sess = self.sessions.get(self.speaking)
                    if sess and self.speaking in self.open_activity:
                        await self.send_safely(sess, activity_end=types.ActivityEnd())
                        self.open_activity.discard(self.speaking)
        except WebSocketDisconnect:
            log.info("멀티콜 클라이언트 종료")
        except Exception as e:
            log.info(f"멀티콜 클라이언트 수신 종료: {e}")
        finally:
            self.client_gone.set()

    async def send_safely(self, sess, **kw):
        """세션이 막 끊긴 순간의 전송 실패로 통화가 끝나면 안 된다. member() 가 이어받는다."""
        try:
            await sess.send_realtime_input(**kw)
        except Exception as e:
            log.info(f"세션 전송 실패, 갈아타기를 기다린다: {e}")


@router.websocket("/ws/room")
async def room_socket(websocket: WebSocket):
    await websocket.accept()
    try:
        join = json.loads(await websocket.receive_text())
        card_ids = join.get("cardIds", [])
        cards = [c for c in (db.get_card(i) for i in card_ids) if c]
        if not cards:
            await websocket.send_text(json.dumps({"type": "error", "data": "카드가 없습니다"}))
            await websocket.close()
            return

        log.info(f"멀티콜 시작: {', '.join(c['name'] for c in cards)}")
        import time, uuid
        room_id = uuid.uuid4().hex[:12]
        started = time.time()
        try:
            db.log_event("room_start", card_id=cards[0]["card_id"], session_id=room_id,
                         meta={"members": [c["card_id"] for c in cards], "size": len(cards)})
        except Exception as e:
            log.warning(f"room_start 로그 실패: {e}")
        client = genai.Client(vertexai=True, project=GCP_PROJECT, location=GCP_LOCATION)
        room = Room(websocket, cards, room_id)

        loop = asyncio.get_running_loop()
        readies = [loop.create_future() for _ in cards]
        tasks = [
            asyncio.create_task(room.member(
                c, [o for o in cards if o["card_id"] != c["card_id"]], client, ready))
            for c, ready in zip(cards, readies)
        ]
        reader = None
        try:
            await asyncio.gather(*readies)

            await websocket.send_text(json.dumps({
                "type": "joined",
                "members": [{
                    "cardId": c["card_id"], "name": c["name"], "voice": c["voice"],
                    "faceId": (call.avatar_of(c) or {}).get("faceId"),
                    "avatar": call.avatar_of(c),
                    "image": c["image_path"],
                } for c in cards],
            }))

            reader = asyncio.create_task(room.from_client())
            await room.client_gone.wait()
        finally:
            room.client_gone.set()
            try:
                db.log_event("room_end", card_id=cards[0]["card_id"], session_id=room_id,
                             meta={"size": len(cards), "seconds": round(time.time() - started, 1),
                                   "relays": room.relay_turn})
            except Exception as e:
                log.warning(f"room_end 로그 실패: {e}")
            if reader:
                reader.cancel()
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, *([reader] if reader else []), return_exceptions=True)
        try:
            await websocket.close()
        except Exception:
            pass

    except Exception as e:
        log.error(f"멀티콜 오류: {e}")
        try:
            await websocket.send_text(json.dumps({"type": "error", "data": str(e)}))
        except Exception:
            pass
        await websocket.close()
