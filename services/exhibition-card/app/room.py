"""
멀티콜 — 발언권 중재 방식.

한 방에 아이돌 여러 명이 들어오지만 동시에 말하면 겹치므로, 서버가 매 턴
'지금 답할 사람' 하나를 정한다. 사람의 음성은 그 한 명에게만 실시간으로 흐르고,
나머지에게는 오간 말을 텍스트로 넣어 맥락만 따라가게 한다.
그래서 다음 차례가 와도 대화를 알고 있다.
"""
import asyncio
import base64
import json
import logging
import os
from contextlib import AsyncExitStack
from pathlib import Path

import google.genai as genai
from dotenv import load_dotenv
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from google.genai import types

from . import db

load_dotenv(Path(__file__).parent.parent / ".env")
GCP_PROJECT = os.getenv("GCP_PROJECT", "project-8f215caa-065e-4ffe-ac9")
GCP_LOCATION = os.getenv("GCP_LOCATION", "us-central1")
LIVE_MODEL = os.getenv("LIVE_MODEL", "gemini-live-2.5-flash-native-audio")

log = logging.getLogger("room")

# 사람 발화 한 번당 아이돌끼리 주고받을 최대 횟수
MAX_RELAYS = 2
router = APIRouter()


def build_config(card, others):
    """다른 멤버가 누구인지 알려줘야 서로를 아는 대화가 된다."""
    persona = card["persona"]
    if others:
        names = ", ".join(o["name"] for o in others)
        persona += (
            f"\n\n지금 {names}와(과) 함께 단체 영상통화 중이야. "
            f"상대가 한 말은 '(이름): 내용' 형태로 전달돼. "
            f"네 차례에만 말하고, 다른 사람 말에 자연스럽게 반응해. "
            f"이름을 부르며 대화해도 좋아. 짧게 말해."
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
    )


class Room:
    def __init__(self, websocket, cards):
        self.ws = websocket
        self.cards = cards
        self.sessions = {}          # card_id -> live session
        self.turn = 0               # 라운드로빈 커서
        self.target = None          # 클라이언트가 지목한 상대
        self.speaking = None        # 이번 턴 화자
        self.relay_turn = 0         # 아이돌끼리 이어 말할 때의 커서
        self.relays = 0             # 사람 발화 이후 연속 릴레이 횟수
        self.lock = asyncio.Lock()

    def pick_speaker(self):
        """지목이 있으면 그 사람, 없으면 돌아가며."""
        if self.target and self.target in self.sessions:
            return self.target
        cid = self.cards[self.turn % len(self.cards)]["card_id"]
        self.turn += 1
        return cid

    async def inject(self, text, speaker_name, exclude):
        """오간 말을 나머지 멤버의 맥락에 텍스트로 넣는다 (응답은 유발하지 않음)."""
        for cid, sess in self.sessions.items():
            if cid == exclude:
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
        self.relay_turn += 1
        self.relays += 1
        log.info(f"릴레이 {self.relays}/{MAX_RELAYS}: {from_name} → {nxt['name']}")
        await self.ws.send_text(json.dumps({"type": "turn_start", "cardId": nxt["card_id"]}))
        try:
            await self.sessions[nxt["card_id"]].send_client_content(
                turns=types.Content(role="user",
                                    parts=[types.Part(text=f"({from_name}): {text}")]),
                turn_complete=True,   # 이번엔 응답을 유발한다
            )
        except Exception as e:
            log.warning(f"릴레이 실패 {nxt['card_id']}: {e}")

    async def pump(self, card):
        """한 멤버의 응답을 받아 클라이언트로 넘기고, 나머지에게 텍스트로 공유한다."""
        cid, name = card["card_id"], card["name"]
        sess = self.sessions[cid]
        said = []
        try:
            while True:
                async for response in sess.receive():
                    if response.data:
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
                    if getattr(sc, "turn_complete", False):
                        text = "".join(said).strip()
                        said = []
                        await self.ws.send_text(json.dumps({
                            "type": "turn_complete", "cardId": cid, "text": text,
                        }))
                        if text:
                            log.info(f"{name}: {text}")
                            await self.inject(text, name, exclude=cid)
                            # 맥락만 넣으면 대화가 거기서 끊긴다. 한 명은 받아치게 한다.
                            await self.relay(cid, name, text)
                        break
        except Exception as e:
            log.info(f"pump 종료 {cid}: {e}")

    async def from_client(self):
        try:
            while True:
                msg = json.loads(await self.ws.receive_text())
                t = msg.get("type")

                if t == "target":
                    self.target = msg.get("cardId")

                elif t == "activity_start":
                    async with self.lock:
                        self.relays = 0          # 사람이 끼어들면 릴레이를 새로 센다
                        self.speaking = self.pick_speaker()
                    await self.ws.send_text(json.dumps(
                        {"type": "turn_start", "cardId": self.speaking}))
                    await self.sessions[self.speaking].send_realtime_input(
                        activity_start=types.ActivityStart())

                elif t == "audio" and self.speaking:
                    await self.sessions[self.speaking].send_realtime_input(
                        audio=types.Blob(data=base64.b64decode(msg["data"]),
                                         mime_type="audio/pcm;rate=16000"))

                elif t == "activity_end" and self.speaking:
                    await self.sessions[self.speaking].send_realtime_input(
                        activity_end=types.ActivityEnd())
        except WebSocketDisconnect:
            log.info("멀티콜 클라이언트 종료")


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
        room = Room(websocket, cards)

        async with AsyncExitStack() as stack:
            for card in cards:
                others = [c for c in cards if c["card_id"] != card["card_id"]]
                sess = await stack.enter_async_context(
                    client.aio.live.connect(model=LIVE_MODEL, config=build_config(card, others))
                )
                room.sessions[card["card_id"]] = sess

            await websocket.send_text(json.dumps({
                "type": "joined",
                "members": [{
                    "cardId": c["card_id"], "name": c["name"], "voice": c["voice"],
                    "faceId": c["face_id"] if c["face_status"] == "ready" else None,
                    "image": c["image_path"],
                } for c in cards],
            }))

            tasks = [asyncio.create_task(room.pump(c)) for c in cards]
            tasks.append(asyncio.create_task(room.from_client()))
            await asyncio.gather(*tasks, return_exceptions=True)
            try:
                db.log_event("room_end", card_id=cards[0]["card_id"], session_id=room_id,
                             meta={"size": len(cards), "seconds": round(time.time() - started, 1),
                                   "relays": room.relay_turn})
            except Exception as e:
                log.warning(f"room_end 로그 실패: {e}")

    except Exception as e:
        log.error(f"멀티콜 오류: {e}")
        try:
            await websocket.send_text(json.dumps({"type": "error", "data": str(e)}))
        except Exception:
            pass
        await websocket.close()
