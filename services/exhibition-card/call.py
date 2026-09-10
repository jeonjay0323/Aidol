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

import db

load_dotenv(Path(__file__).parent / ".env")

GCP_PROJECT = os.getenv("GCP_PROJECT", "aidol-505503")
GCP_LOCATION = os.getenv("GCP_LOCATION", "us-central1")
LIVE_MODEL = os.getenv("LIVE_MODEL", "gemini-live-2.5-flash-native-audio")

log = logging.getLogger("call")
router = APIRouter()


@router.websocket("/ws/call/{card_id}")
async def call(websocket: WebSocket, card_id: str):
    await websocket.accept()

    card = db.get_card(card_id)
    if not card:
        await websocket.send_text(json.dumps({"type": "error", "data": "카드를 찾을 수 없습니다"}))
        await websocket.close()
        return

    log.info(f"통화 연결: {card['name']} ({card_id}) / face={card['face_status']}")

    client = genai.Client(vertexai=True, project=GCP_PROJECT, location=GCP_LOCATION)
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=card["persona"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=card["voice"])
            )
        ),
        # 클라이언트가 RMS로 발화 구간을 판단한다 (첫 음절 잘림 방지 preroll 포함)
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(disabled=True)
        ),
    )

    try:
        async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
            await websocket.send_text(json.dumps({
                "type": "connected",
                "name": card["name"],
                "faceId": card["face_id"] if card["face_status"] == "ready" else None,
                "mode": "video" if card["face_status"] == "ready" else "voice",
            }))

            async def from_client():
                try:
                    while True:
                        msg = json.loads(await websocket.receive_text())
                        t = msg.get("type")
                        if t == "audio":
                            await session.send_realtime_input(
                                audio=types.Blob(
                                    data=base64.b64decode(msg["data"]),
                                    mime_type="audio/pcm;rate=16000",
                                )
                            )
                        elif t == "activity_start":
                            await session.send_realtime_input(activity_start=types.ActivityStart())
                        elif t == "activity_end":
                            await session.send_realtime_input(activity_end=types.ActivityEnd())
                except WebSocketDisconnect:
                    log.info(f"클라이언트 종료: {card_id}")

            async def to_client():
                try:
                    while True:
                        async for response in session.receive():
                            if response.data:
                                await websocket.send_text(json.dumps({
                                    "type": "audio",
                                    "data": base64.b64encode(response.data).decode(),
                                }))
                            sc = getattr(response, "server_content", None)
                            if sc and getattr(sc, "turn_complete", False):
                                await websocket.send_text(json.dumps({"type": "turn_complete"}))
                                break
                except Exception as e:
                    log.info(f"수신 종료: {e}")

            await asyncio.gather(from_client(), to_client(), return_exceptions=True)

    except Exception as e:
        log.error(f"통화 오류 {card_id}: {e}")
        try:
            await websocket.send_text(json.dumps({"type": "error", "data": str(e)}))
        except Exception:
            pass
        await websocket.close()
