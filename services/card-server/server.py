"""
전시 카드 서버.

카드는 즉시 발급되고 얼굴은 최대 8시간 뒤에 붙는다.
그 간격을 face_status로 표현하고, 스캔 시 상태에 따라 화면을 분기한다.
"""
import io
import json
import logging
import os
from pathlib import Path

import segno
from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import call
import db
import room
import simli

HERE = Path(__file__).parent
load_dotenv(HERE / ".env")

# 카드 QR에 박히는 주소. 전시 배포 시 고정 도메인으로 바꾼다.
BASE_URL = os.getenv("BASE_URL", "").rstrip("/")

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Aidol Exhibition Card")
app.include_router(call.router)
app.include_router(room.router)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")

db.init()


def base_url(request: Request) -> str:
    return BASE_URL or str(request.base_url).rstrip("/")


def card_or_404(card_id):
    card = db.get_card(card_id)
    if not card:
        raise HTTPException(404, f"카드를 찾을 수 없습니다: {card_id}")
    return card


# ── 카드 발급 ─────────────────────────────────────────────
@app.post("/api/cards")
async def create_card(
    name: str = Form(...),
    persona: str = Form(...),
    voice: str = Form("Puck"),
    tags: str = Form("[]"),
    stats: str = Form("{}"),
    source: str = Form("user"),
    image: UploadFile = File(None),
):
    """
    companion-creator가 호출하는 엔드포인트.
    이미지를 함께 주면 얼굴 등록까지 바로 걸어둔다 (카드 발급은 기다리지 않는다).
    """
    card_id = db.create_card(
        name=name, persona=persona, voice=voice,
        tags=json.loads(tags), stats=json.loads(stats), source=source,
    )

    warnings = []
    if image is not None:
        data = await image.read()
        path = HERE / "static" / "faces" / f"{card_id}.png"
        path.write_bytes(data)
        db.set_face(card_id, face_status="none")
        with db.connect() as con:
            con.execute("UPDATE cards SET image_path=? WHERE card_id=?",
                        (f"/static/faces/{card_id}.png", card_id))
        try:
            face_id, warnings = simli.submit_face(data, card_id, image.filename or "face.png")
            db.set_face(card_id, face_id=face_id, face_status="processing")
        except Exception as e:
            # 얼굴 등록이 실패해도 카드는 나가야 한다. 음성 통화로 폴백된다.
            db.set_face(card_id, face_status="failed")
            warnings = [f"얼굴 등록 실패: {e}"]

    card = db.get_card(card_id)
    return JSONResponse({
        "cardId": card_id,
        "scanUrl": f"/c/{card_id}",
        "faceStatus": card["face_status"],
        "warnings": warnings,
    })


@app.get("/api/cards")
async def api_list(source: str = None, face_status: str = None):
    return db.list_cards(source=source, face_status=face_status)


@app.get("/api/cards/{card_id}")
async def api_get(card_id: str):
    card = card_or_404(card_id)
    # persona와 owner_token은 통화 서버만 쓰는 값이라 내려보내지 않는다
    card.pop("persona", None)
    card.pop("owner_token", None)
    return card


@app.get("/api/cards/{card_id}/call")
async def api_call_config(card_id: str):
    """통화 엔진이 세션을 열 때 필요한 세 값."""
    card = card_or_404(card_id)
    if card["face_status"] != "ready":
        return {"mode": "voice", "persona": card["persona"], "voice": card["voice"],
                "faceId": None, "reason": card["face_status"]}
    return {"mode": "video", "persona": card["persona"], "voice": card["voice"],
            "faceId": card["face_id"]}


# ── 화면 ─────────────────────────────────────────────────
@app.get("/c/{card_id}", response_class=HTMLResponse)
async def scan_landing(request: Request, card_id: str):
    card = card_or_404(card_id)
    card.pop("persona", None)
    card.pop("owner_token", None)
    return templates.TemplateResponse("scan.html", {
        "request": request, "card": card, "card_json": json.dumps(card, ensure_ascii=False),
    })


@app.get("/card/{card_id}", response_class=HTMLResponse)
async def printable_card(request: Request, card_id: str):
    card = card_or_404(card_id)
    return templates.TemplateResponse("card.html", {
        "request": request, "card": card,
        "qr_url": f"/qr/{card_id}.png",
    })


@app.get("/admin", response_class=HTMLResponse)
async def admin(request: Request):
    """카드 목록 · NFC 쓰기. 안드로이드 Chrome에서 열어야 NFC가 동작한다."""
    return templates.TemplateResponse("admin.html", {
        "request": request, "cards": db.list_cards(), "base_url": base_url(request),
    })


@app.get("/qr/{card_id}.png")
async def qr_png(request: Request, card_id: str):
    card_or_404(card_id)
    url = f"{base_url(request)}/c/{card_id}"
    qr = segno.make(url, error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="png", scale=20, border=2, dark="#2b1d14", light="#f2e6d2")
    return Response(buf.getvalue(), media_type="image/png")


@app.post("/api/simli/token")
async def simli_token(payload: dict):
    """클라이언트가 Simli에 직접 붙되, API 키는 서버에만 둔다."""
    import requests
    r = requests.post(
        "https://api.simli.ai/compose/token",
        headers={"x-simli-api-key": simli.KEY, "Content-Type": "application/json"},
        json={
            "faceId": payload.get("faceId"),
            "apiVersion": "v2",
            "handleSilence": True,
            "audioInputFormat": "pcm16",
            "maxSessionLength": 1800,
            "maxIdleTime": 300,
        },
        timeout=30,
    )
    return JSONResponse(r.json(), status_code=r.status_code)


@app.get("/api/simli/ice")
async def simli_ice():
    import requests
    r = requests.get("https://api.simli.ai/compose/ice",
                     headers={"x-simli-api-key": simli.KEY}, timeout=30)
    return JSONResponse(r.json(), status_code=r.status_code)


@app.get("/health")
async def health():
    cards = db.list_cards()
    by_status = {}
    for c in cards:
        by_status[c["face_status"]] = by_status.get(c["face_status"], 0) + 1
    return {"cards": len(cards), "faceStatus": by_status}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


# ── 로비 · 초대 ────────────────────────────────────────────
# iOS는 웹에서 NFC를 읽을 수 없다. 대신 카드를 탭하면 그 카드 페이지가 열리므로,
# "지금 열려 있는 로비"를 서버가 알고 있다가 그 페이지에서 참여를 받는다.
_LOBBIES = {}   # host_card_id -> {"opened": ts, "invites": [card_id, ...]}
LOBBY_TTL = 300


def _sweep():
    import time
    now = time.time()
    for k in [k for k, v in _LOBBIES.items() if now - v["opened"] > LOBBY_TTL]:
        _LOBBIES.pop(k, None)


@app.post("/api/lobby/{card_id}/open")
async def lobby_open(card_id: str):
    """호스트가 멀티콜 로비를 열었음을 알린다. 주기적으로 갱신해 살아있음을 표시."""
    import time
    card_or_404(card_id)
    _sweep()
    entry = _LOBBIES.setdefault(card_id, {"opened": time.time(), "invites": []})
    entry["opened"] = time.time()
    return {"ok": True}


@app.get("/api/lobby/open")
async def lobby_current():
    """지금 열려 있는 로비. 전시 부스가 하나라는 전제로 가장 최근 것을 돌려준다."""
    _sweep()
    if not _LOBBIES:
        return {"host": None}
    host_id = max(_LOBBIES, key=lambda k: _LOBBIES[k]["opened"])
    host = db.get_card(host_id)
    return {"host": {"cardId": host_id, "name": host["name"]} if host else None}


@app.post("/api/lobby/{host_id}/join")
async def lobby_join(host_id: str, payload: dict):
    """게스트 카드가 참여를 신청한다."""
    _sweep()
    guest_id = payload.get("cardId")
    if host_id not in _LOBBIES:
        raise HTTPException(404, "열려 있는 통화가 없습니다")
    card_or_404(guest_id)
    invites = _LOBBIES[host_id]["invites"]
    if guest_id not in invites:
        invites.append(guest_id)
    return {"ok": True}


@app.get("/api/lobby/{host_id}/invites")
async def lobby_invites(host_id: str):
    """호스트가 대기 중인 참여 신청을 가져간다."""
    _sweep()
    ids = _LOBBIES.get(host_id, {}).get("invites", [])
    return [db.get_card(i) for i in ids if db.get_card(i)]
