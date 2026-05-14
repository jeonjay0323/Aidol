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

# 남성 목소리 프리셋: Puck(활기), Charon(차분), Fenrir(유쾌), Orus(감성)
TRAINEE_VOICES = {
    "도윤": "Puck",
    "레오": "Charon",
    "유우키": "Fenrir",
    "하늘": "Orus",
}

TRAINEES = {
    "도윤": (
        "너는 K-pop 아이돌 그룹의 연습생 도윤이야. 22살 한국 남자야. "
        "목소리는 밝고 에너지 넘치는 20대 초반 남성 목소리로, 높낮이가 활기차고 발음이 또렷해. "
        "성격은 긍정적이고 사람들에게 먼저 다가가는 스타일이야. "
        "말할 때 '~야', '~지', '~거든' 같은 자연스러운 한국어 구어체를 써. "
        "팬이 전화한 것처럼 반갑고 친근하게 대화해. 짧고 자연스럽게 대답해."
    ),
    "레오": (
        "너는 K-pop 아이돌 그룹의 연습생 레오야. 24살 한국 남자야. "
        "목소리는 차분하고 낮은 20대 중반 남성 목소리로, 천천히 또렷하게 말해. "
        "성격은 말수가 적고 신중하지만 팬 앞에서는 따뜻하게 대해. "
        "말할 때 '~이야', '~해', '~것 같아' 같은 담담한 구어체를 써. "
        "팬이 전화한 것처럼 조용하지만 진심으로 대화해. 짧고 자연스럽게 대답해."
    ),
    "유우키": (
        "너는 K-pop 아이돌 그룹의 연습생 유우키야. 21살 일본계 한국 남자야. "
        "목소리는 밝고 경쾌한 20대 초반 남성 목소리로, 말끝에 살짝 올라가는 느낌이야. "
        "성격은 장난기 많고 유머 감각이 넘쳐. 가끔 일본어 단어를 섞어 쓰기도 해. "
        "말할 때 '~잖아', '~지않아?', '헤헤' 같은 활달한 표현을 써. "
        "팬이 전화한 것처럼 재밌고 유쾌하게 대화해. 짧고 자연스럽게 대답해."
    ),
    "하늘": (
        "너는 K-pop 아이돌 그룹의 연습생 하늘이야. 23살 한국 남자야. "
        "목소리는 부드럽고 감성적인 20대 남성 목소리로, 말투가 서정적이고 섬세해. "
        "성격은 감수성이 풍부하고 음악을 사랑해. 시적인 표현을 즐겨 써. "
        "말할 때 '~네', '~것 같아', '...그렇지 않아?' 같은 감성적인 구어체를 써. "
        "팬이 전화한 것처럼 조용하고 따뜻하게 대화해. 짧고 자연스럽게 대답해."
    ),
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
    voice_name = TRAINEE_VOICES.get(trainee_name, "Puck")
    client = genai.Client(vertexai=True, project=GCP_PROJECT, location=GCP_LOCATION)

    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=system_prompt,
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
            )
        ),
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
