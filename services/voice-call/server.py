import asyncio
import base64
import json
import logging
import os
import urllib.request
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
import google.genai as genai
from google.genai import types

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("trainee")

app = FastAPI()
GCP_PROJECT = "project-0cc445dc-b940-4148-849"
GCP_LOCATION = "us-central1"
MODEL = "gemini-live-2.5-flash-native-audio"
SIMLI_API_KEY = os.getenv("SIMLI_API_KEY", "")

TRAINEES = {
    "도윤": "너는 K-pop 아이돌 연습생 도윤이야. 밝고 에너지 넘치는 성격이야. 한국어로 자연스럽게 대화해. 팬과 통화하는 것처럼 친근하게 말해.",
    "레오": "너는 K-pop 아이돌 연습생 레오야. 차분하고 성숙한 분위기야. 한국어로 자연스럽게 대화해. 팬과 통화하는 것처럼 친근하게 말해.",
    "유우키": "너는 K-pop 아이돌 연습생 유우키야. 장난기 많고 유쾌한 성격이야. 한국어로 자연스럽게 대화해. 팬과 통화하는 것처럼 친근하게 말해.",
    "하늘": "너는 K-pop 아이돌 연습생 하늘이야. 조용하고 감성적인 성격이야. 한국어로 자연스럽게 대화해. 팬과 통화하는 것처럼 친근하게 말해.",
}


@app.get("/", response_class=HTMLResponse)
async def root():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/pcm-processor.js")
async def worklet():
    return FileResponse("pcm-processor.js", media_type="application/javascript")


@app.get("/favicon.ico")
async def favicon():
    return FileResponse("favicon.ico") if os.path.exists("favicon.ico") else HTMLResponse("", status_code=204)


@app.get("/trainees")
async def get_trainees():
    return list(TRAINEES.keys())


@app.post("/simli-token")
async def get_simli_token(body: dict):
    face_id = body.get("faceId")
    payload = json.dumps({
        "faceId": face_id,
        "apiVersion": "v2",
        "handleSilence": True,
        "audioInputFormat": "pcm16",
        "maxSessionLength": 3600,
        "maxIdleTime": 300,
    }).encode()
    req = urllib.request.Request(
        "https://api.simli.ai/compose/token",
        data=payload,
        headers={
            "x-simli-api-key": SIMLI_API_KEY,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        result = json.loads(r.read())
    log.info(f"Simli 토큰 발급: {face_id}")
    return JSONResponse(result)


@app.websocket("/ws/{trainee_name}")
async def websocket_endpoint(websocket: WebSocket, trainee_name: str):
    await websocket.accept()
    log.info(f"WebSocket 연결: {trainee_name}")

    system_prompt = TRAINEES.get(trainee_name, list(TRAINEES.values())[0])
    client = genai.Client(vertexai=True, project=GCP_PROJECT, location=GCP_LOCATION)

    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=system_prompt,
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(
                disabled=True
            )
        ),
    )

    try:
        async with client.aio.live.connect(model=MODEL, config=config) as session:
            log.info("Gemini Live 세션 연결됨")
            await websocket.send_text(json.dumps({"type": "connected"}))

            async def receive_from_client():
                audio_chunks = 0
                try:
                    while True:
                        data = await websocket.receive_text()
                        msg = json.loads(data)
                        if msg["type"] == "audio":
                            audio_bytes = base64.b64decode(msg["data"])
                            audio_chunks += 1
                            if audio_chunks % 20 == 0:
                                log.info(f"오디오 수신: {audio_chunks}청크")
                            await session.send_realtime_input(
                                audio=types.Blob(
                                    data=audio_bytes,
                                    mime_type="audio/pcm;rate=16000"
                                )
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
                    while True:  # 턴마다 session.receive()를 다시 호출
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
                                    break  # inner loop 탈출 → while True로 다시 receive()
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
