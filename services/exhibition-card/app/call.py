"""
카드 ID로 거는 1:1 영상통화.

solo-call의 구조를 그대로 쓰되, 페르소나·목소리를 하드코딩 dict가 아니라
카드 DB에서 읽는다. 얼굴(faceId)은 클라이언트가 Simli에 직접 붙을 때 쓴다.
"""
import asyncio
import base64
import json
import logging
import os
from pathlib import Path

import google.genai as genai
from dotenv import load_dotenv
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from google.genai import types

from . import db, expr, kids

load_dotenv(Path(__file__).parent.parent / ".env")

GCP_PROJECT = os.getenv("GCP_PROJECT", "project-d4a769de-d13f-4a6a-a22")
GCP_LOCATION = os.getenv("GCP_LOCATION", "us-central1")
LIVE_MODEL = os.getenv("LIVE_MODEL", "gemini-live-2.5-flash-native-audio")

MAX_RECONNECT = 3   # Gemini 재연결을 이만큼 연달아 실패하면 통화를 끝낸다

log = logging.getLogger("call")
router = APIRouter()


def avatar_of(card):
    """영상으로 보여줄 아바타. 없으면 None(음성 통화).

    photo: Simli 얼굴이 준비된 경우 — 클라이언트가 Simli WebRTC에 붙는다
    vrm:   모델 파일 URL — 클라이언트가 three-vrm으로 직접 그린다
    """
    if kids.KIDS_MODE:
        return None   # 아이용 모드는 늘 음성 통화 (app/kids.py)
    if expr.of(card):
        return None   # 표정 세트가 있으면 큰 사진 + 표정 전환으로 (app/expr.py)
    if card["face_status"] != "ready":
        return None
    if card.get("avatar_type") == "vrm":
        if not card.get("model_path"):
            return None
        return {"type": "vrm", "url": card["model_path"],
                "colors": (card.get("custom") or {}).get("colors", {})}
    return {"type": "photo", "faceId": card["face_id"]} if card.get("face_id") else None


SPEECH = {
    "casual": "반말로 친구처럼 편하게 말해.",
    "polite": "존댓말로 다정하게 말해.",
}


def persona_of(card):
    """카드 페르소나에 주인이 꾸민 말투 · 호칭 · 한 줄 설정을 덧붙인다."""
    c = card.get("custom") or {}
    extra = []
    if c.get("speech") in SPEECH:
        extra.append(SPEECH[c["speech"]])
    if c.get("callme"):
        extra.append(f"상대를 '{c['callme']}'(이)라고 불러.")
    if c.get("note"):
        extra.append(f"주인이 정해준 설정: {c['note']}")
    base = card["persona"] + ("\n\n" + "\n".join(extra) if extra else "")
    return kids.apply(base)


@router.websocket("/ws/call/{card_id}")
async def call(websocket: WebSocket, card_id: str):
    await websocket.accept()

    card = db.get_card(card_id)
    if not card:
        await websocket.send_text(json.dumps({"type": "error", "data": "카드를 찾을 수 없습니다"}))
        await websocket.close()
        return

    log.info(f"통화 연결: {card['name']} ({card_id}) / face={card['face_status']}")
    import time, uuid
    session_id = uuid.uuid4().hex[:12]
    started = time.time()
    avatar = avatar_of(card)
    mode = "video" if avatar else "voice"
    turns = 0
    try:
        db.log_event("call_start", card_id=card_id, session_id=session_id,
                     meta={"mode": mode, "avatar": card.get("avatar_type", "photo")})
    except Exception as e:
        log.warning(f"call_start 로그 실패: {e}")

    client = genai.Client(vertexai=True, project=GCP_PROJECT, location=GCP_LOCATION)

    def live_config(handle=None):
        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=persona_of(card),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=card["voice"])
                )
            ),
            # 클라이언트가 RMS로 발화 구간을 판단한다 (첫 음절 잘림 방지 preroll 포함)
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(disabled=True)
            ),
            # 아이돌이 하는 말을 글자로도 받는다 — 화면이 말에 맞춰 표정을 고른다
            output_audio_transcription=types.AudioTranscriptionConfig(),
            # Gemini 세션은 약 10분이면 서버가 끊는다. 대화 내용을 이어받아 통화는 유지한다
            session_resumption=types.SessionResumptionConfig(handle=handle),
            context_window_compression=types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow()
            ),
        )

    session = None            # 지금 살아 있는 Gemini 세션. 갈아타는 동안에는 None
    handle = None             # 이어받기 토큰
    user_speaking = False     # 클라이언트 기준 발화 중
    activity_open = False     # 지금 세션에 activity_start 를 보낸 상태
    turn_active = False       # 아이돌이 말하는 중
    client_gone = asyncio.Event()

    async def from_client():
        nonlocal user_speaking, activity_open
        try:
            while True:
                msg = json.loads(await websocket.receive_text())
                t = msg.get("type")
                if t == "activity_start":
                    user_speaking = True
                elif t == "activity_end":
                    user_speaking = False
                s = session
                if s is None:
                    continue   # 갈아타는 1~2초 동안의 소리는 버린다
                try:
                    if t == "audio":
                        await s.send_realtime_input(
                            audio=types.Blob(
                                data=base64.b64decode(msg["data"]),
                                mime_type="audio/pcm;rate=16000",
                            )
                        )
                    elif t == "activity_start":
                        await s.send_realtime_input(activity_start=types.ActivityStart())
                        activity_open = True
                    elif t == "activity_end" and activity_open:
                        await s.send_realtime_input(activity_end=types.ActivityEnd())
                        activity_open = False
                except Exception as e:
                    log.info(f"세션 전송 실패, 갈아타기를 기다린다: {e}")
        except WebSocketDisconnect:
            log.info(f"클라이언트 종료: {card_id}")
        except Exception as e:
            log.info(f"클라이언트 수신 종료: {e}")
        finally:
            client_gone.set()

    async def to_client(s):
        """세션이 끝나면 돌아온다. 호출한 쪽이 이어받아 다시 연다."""
        nonlocal handle, turn_active, turns
        leaving = False
        try:
            while True:
                async for response in s.receive():
                    update = getattr(response, "session_resumption_update", None)
                    if update and update.resumable and update.new_handle:
                        handle = update.new_handle
                    if getattr(response, "go_away", None):
                        log.info(f"Gemini 세션 만료 예고: {card_id}")
                        leaving = True
                    if response.data:
                        turn_active = True
                        await websocket.send_text(json.dumps({
                            "type": "audio",
                            "data": base64.b64encode(response.data).decode(),
                        }))
                    sc = getattr(response, "server_content", None)
                    tr = getattr(sc, "output_transcription", None) if sc else None
                    if tr and getattr(tr, "text", None):
                        await websocket.send_text(json.dumps({"type": "text", "text": tr.text}))
                    if sc and getattr(sc, "turn_complete", False):
                        turns += 1
                        turn_active = False
                        await websocket.send_text(json.dumps({"type": "turn_complete"}))
                    # 말이 오가지 않는 틈에 갈아타야 끊김이 들리지 않는다
                    if leaving and not turn_active and not user_speaking:
                        return
        except Exception as e:
            log.info(f"수신 종료: {e}")

    reader = asyncio.create_task(from_client())
    connected = False
    failures = 0
    try:
        while not client_gone.is_set():
            try:
                async with client.aio.live.connect(model=LIVE_MODEL, config=live_config(handle)) as s:
                    if not connected:
                        await websocket.send_text(json.dumps({
                            "type": "connected",
                            "name": card["name"],
                            "faceId": avatar.get("faceId") if avatar else None,
                            "avatar": avatar,
                            "mode": mode,
                        }))
                        connected = True
                    else:
                        log.info(f"Gemini 세션 이어받음: {card_id}")
                    failures = 0
                    activity_open = False
                    if user_speaking:
                        await s.send_realtime_input(activity_start=types.ActivityStart())
                        activity_open = True
                    session = s
                    relay = asyncio.create_task(to_client(s))
                    gone = asyncio.create_task(client_gone.wait())
                    try:
                        await asyncio.wait({relay, gone}, return_when=asyncio.FIRST_COMPLETED)
                    finally:
                        session = None
                        relay.cancel()
                        gone.cancel()
                        await asyncio.gather(relay, gone, return_exceptions=True)
            except Exception as e:
                if client_gone.is_set():
                    break
                if not connected:
                    raise
                failures += 1
                log.warning(f"Gemini 재연결 실패 {failures}/{MAX_RECONNECT}: {e}")
                if failures >= MAX_RECONNECT:
                    raise
                await asyncio.sleep(failures)
                continue
            # 말하던 중에 끊겼으면 그 턴은 닫아 준다. 화면이 대답 중에 멈춰 있지 않도록
            if turn_active and not client_gone.is_set():
                turn_active = False
                await websocket.send_text(json.dumps({"type": "turn_complete"}))
    except Exception as e:
        log.error(f"통화 오류 {card_id}: {e}")
        try:
            await websocket.send_text(json.dumps({"type": "error", "data": str(e)}))
        except Exception:
            pass
    finally:
        reader.cancel()
        try:
            db.log_event("call_end", card_id=card_id, session_id=session_id,
                         meta={"mode": mode, "seconds": round(time.time() - started, 1),
                               "turns": turns})
        except Exception as e:
            log.warning(f"call_end 로그 실패: {e}")
        await asyncio.gather(reader, return_exceptions=True)
        try:
            await websocket.close()
        except Exception:
            pass
