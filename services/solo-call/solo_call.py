import asyncio
import base64
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import google.genai as genai
from google.genai import types

from config import GCP_PROJECT, GCP_LOCATION, LIVE_MODEL, TRAINEE_VOICES, TRAINEES

log = logging.getLogger("trainee")
router = APIRouter()


@router.websocket("/ws/{trainee_name}")
async def solo_call(websocket: WebSocket, trainee_name: str):
    await websocket.accept()
    log.info(f"1:1 통화 연결: {trainee_name}")

    system_prompt = TRAINEES.get(trainee_name, list(TRAINEES.values())[0])
    voice_name    = TRAINEE_VOICES.get(trainee_name, "Puck")
    client        = genai.Client(vertexai=True, project=GCP_PROJECT, location=GCP_LOCATION)

    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=system_prompt,
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
            )
        ),
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(disabled=True)
        ),
    )

    try:
        async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
            log.info("Gemini Live 세션 연결됨")
            await websocket.send_text(json.dumps({"type": "connected"}))

            async def receive_from_client():
                audio_chunks = 0
                try:
                    while True:
                        data = await websocket.receive_text()
                        msg  = json.loads(data)
                        if msg["type"] == "audio":
                            audio_bytes   = base64.b64decode(msg["data"])
                            audio_chunks += 1
                            if audio_chunks % 20 == 0:
                                log.info(f"오디오 수신: {audio_chunks}청크")
                            await session.send_realtime_input(
                                audio=types.Blob(data=audio_bytes, mime_type="audio/pcm;rate=16000")
                            )
                        elif msg["type"] == "activity_start":
                            log.info("발화 시작")
                            await session.send_realtime_input(activity_start=types.ActivityStart())
                        elif msg["type"] == "activity_end":
                            log.info("발화 종료")
                            await session.send_realtime_input(activity_end=types.ActivityEnd())
                except WebSocketDisconnect:
                    log.info("클라이언트 연결 종료")

            async def send_to_client():
                response_count = 0
                log.info("send_to_client 시작")
                try:
                    while True:
                        async for response in session.receive():
                            if response.data:
                                response_count += 1
                                log.info(f"AI 응답 #{response_count}: {len(response.data)}bytes")
                                await websocket.send_text(json.dumps({
                                    "type": "audio",
                                    "data": base64.b64encode(response.data).decode()
                                }))
                            if hasattr(response, 'server_content') and response.server_content:
                                if getattr(response.server_content, 'turn_complete', False):
                                    log.info("AI 턴 완료 — 다음 발화 대기")
                                    await websocket.send_text(json.dumps({"type": "turn_complete"}))
                                    break
                except Exception as e:
                    log.error(f"send_to_client 종료: {e}")

            results = await asyncio.gather(
                receive_from_client(),
                send_to_client(),
                return_exceptions=True
            )
            log.info(f"gather 종료: {results}")

    except Exception as e:
        log.error(f"세션 오류: {e}")
        try:
            await websocket.send_text(json.dumps({"type": "error", "data": str(e)}))
        except Exception:
            pass
        await websocket.close()
