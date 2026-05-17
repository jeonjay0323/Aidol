import json
import logging
import os
import urllib.request

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse

from config import TRAINEES, SIMLI_API_KEY
from solo_call import router as solo_router
from duo_chat import router as duo_router

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("trainee")

app = FastAPI()
app.include_router(duo_router)   # /ws/duo 먼저 등록
app.include_router(solo_router)  # /ws/{trainee_name} 나중에


@app.get("/", response_class=HTMLResponse)
async def root():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/duo", response_class=HTMLResponse)
async def duo_page():
    with open("duo.html", "r", encoding="utf-8") as f:
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
        headers={"x-simli-api-key": SIMLI_API_KEY, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        result = json.loads(r.read())
    log.info(f"Simli 토큰 발급: {face_id}")
    return JSONResponse(result)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
