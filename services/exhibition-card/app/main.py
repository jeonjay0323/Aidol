"""
전시 카드 서버.

카드는 즉시 발급되고 얼굴은 최대 8시간 뒤에 붙는다.
그 간격을 face_status로 표현하고, 스캔 시 상태에 따라 화면을 분기한다.
"""
import asyncio
import base64
import io
import json
import logging
import os
import re
from pathlib import Path

import segno
from dotenv import load_dotenv
from fastapi import FastAPI, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

HERE = Path(__file__).parent
# call · room · db 가 import 될 때 GCP_PROJECT 를 읽는다. 그보다 먼저 .env 를 올린다.
load_dotenv(HERE.parent / ".env")

from . import call, db, imagegen, room, simli  # noqa: E402

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
    model: UploadFile = File(None),
    register_face: bool = Form(True),
):
    """
    companion-creator가 호출하는 엔드포인트.
    이미지를 함께 주면 얼굴 등록까지 바로 걸어둔다 (카드 발급은 기다리지 않는다).
    model(.vrm)을 주면 버추얼 카드가 된다. 이때 이미지는 카드 썸네일로만 쓰고
    Simli 등록은 건너뛴다 — 브라우저가 모델을 직접 그리므로 바로 영상통화가 된다.
    register_face=false 면 사진 카드도 등록 없이 음성 통화 카드로 나간다(만들기 화면).
    이때 사진은 DB 에 둔다 — Cloud Run 파일시스템은 재시작하면 사라지는데 인쇄는 나중에도 해야 한다.
    """
    is_vrm = model is not None
    has_image = image is not None
    thumb = None
    if image is not None and not register_face and not is_vrm:
        thumb = await image.read()
        if not thumb.startswith(b"\xff\xd8") or len(thumb) > 700_000:
            raise HTTPException(400, "JPEG 700KB 이하만 받습니다")
    card_id = db.create_card(
        name=name, persona=persona, voice=voice,
        tags=json.loads(tags), stats=json.loads(stats), source=source,
        avatar_type="vrm" if is_vrm else "photo",
    )

    warnings = []
    if is_vrm:
        models = HERE / "static" / "models"
        models.mkdir(exist_ok=True)
        (models / f"{card_id}.vrm").write_bytes(await model.read())
        db.set_media(card_id, model_path=f"/static/models/{card_id}.vrm")
        db.set_face(card_id, face_status="ready")

    if thumb is not None:
        db.set_thumb(card_id, thumb)
        db.set_media(card_id, image_path=f"/thumb/{card_id}.jpg")
        image = None   # 아래 파일 저장 · Simli 등록을 건너뛴다
    if image is not None:
        data = await image.read()
        path = HERE / "static" / "faces" / f"{card_id}.png"
        path.write_bytes(data)
        db.set_media(card_id, image_path=f"/static/faces/{card_id}.png")
    if image is not None and not is_vrm:
        db.set_face(card_id, face_status="none")
        try:
            face_id, warnings = simli.submit_face(data, card_id, image.filename or "face.png")
            db.set_face(card_id, face_id=face_id, face_status="processing")
        except Exception as e:
            # 얼굴 등록이 실패해도 카드는 나가야 한다. 음성 통화로 폴백된다.
            db.set_face(card_id, face_status="failed")
            warnings = [f"얼굴 등록 실패: {e}"]

    card = db.get_card(card_id)
    try:
        db.log_event("card_issued", card_id=card_id,
                     meta={"source": source, "hasImage": has_image, "faceReg": register_face,
                           "avatar": "vrm" if is_vrm else "photo"})
    except Exception as e:
        logging.warning(f"card_issued 로그 실패: {e}")
    return JSONResponse({
        "cardId": card_id,
        "scanUrl": f"/c/{card_id}",
        "faceStatus": card["face_status"],
        "avatarType": card["avatar_type"],
        "warnings": warnings,
    })


@app.post("/api/generate")
async def api_generate(spec: dict):
    """만들기 화면의 조합 + 프롬프트로 카드 사진을 만든다. 저장하지 않고 돌려만 준다.
    관람객이 마음에 들 때까지 다시 뽑고, 고른 한 장을 /api/cards 에 실어 발급한다."""
    try:
        imagegen.build(spec)
    except ValueError as e:
        raise HTTPException(400, str(e))
    try:
        data = await asyncio.to_thread(imagegen.generate, spec)
        ok = True
    except RuntimeError as e:
        ok, data = False, str(e)
    try:
        db.log_event("generate", meta={
            "kind": spec.get("kind"), "grade": spec.get("grade"), "ok": ok,
            "promptLen": len(str(spec.get("prompt") or "")),
            "depth": str(spec.get("depth"))[:4], "try": spec.get("try"),
        })
    except Exception as e:
        logging.warning(f"generate 로그 실패: {e}")
    if not ok:
        raise HTTPException(502, data)
    return {"image": "data:image/jpeg;base64," + base64.b64encode(data).decode()}


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
    av = call.avatar_of(card)
    if not av:
        return {"mode": "voice", "persona": card["persona"], "voice": card["voice"],
                "faceId": None, "avatar": None, "reason": card["face_status"]}
    return {"mode": "video", "persona": card["persona"], "voice": card["voice"],
            "faceId": av.get("faceId"), "avatar": av}


# ── 꾸미기 ───────────────────────────────────────────────
COLOR_PARTS = {"hair", "eye", "top", "bottom", "shoes"}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


@app.post("/api/cards/{card_id}/custom")
async def api_custom(card_id: str, payload: dict):
    """버추얼 카드의 색 · 말투 · 호칭 · 한 줄 설정. 다음 통화부터 반영된다."""
    card = card_or_404(card_id)
    colors = {k: v for k, v in (payload.get("colors") or {}).items()
              if k in COLOR_PARTS and isinstance(v, str) and HEX.match(v)}
    custom = {
        "colors": colors,
        "speech": payload.get("speech") if payload.get("speech") in call.SPEECH else None,
        "callme": str(payload.get("callme") or "").strip()[:10],
        "note": str(payload.get("note") or "").strip()[:100],
    }
    db.set_custom(card_id, custom)
    try:
        before = card.get("custom") or {}
        db.log_event("customize", card_id=card_id, meta={
            "parts": sorted(colors), "speech": custom["speech"],
            "callme": bool(custom["callme"]), "noteLen": len(custom["note"]),
            "first": not before,
        })
    except Exception as e:
        logging.warning(f"customize 로그 실패: {e}")
    return custom


@app.post("/api/cards/{card_id}/thumb")
async def api_thumb(card_id: str, request: Request):
    """꾸민 모습을 브라우저가 찍어 올린다. 카드 · 로비 · 멀티콜 화면이 이 이미지를 쓴다."""
    card = card_or_404(card_id)
    if card.get("avatar_type") != "vrm":
        raise HTTPException(400, "버추얼 카드만 올릴 수 있습니다")
    data = await request.body()
    # Firestore 문서 한도(1MB) 안쪽. JPEG 시그니처만 받는다.
    if not data.startswith(b"\xff\xd8") or len(data) > 700_000:
        raise HTTPException(400, "JPEG 700KB 이하만 받습니다")
    db.set_thumb(card_id, data)
    return {"imagePath": db.get_card(card_id)["image_path"]}


@app.get("/thumb/{card_id}.jpg")
async def thumb(card_id: str):
    data = db.get_thumb(card_id)
    if not data:
        raise HTTPException(404)
    # 주소에 버전(?v=)이 붙어 있어 바뀌면 새 주소가 된다. 오래 캐시해도 된다.
    return Response(data, media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=31536000, immutable"})


# ── 화면 ─────────────────────────────────────────────────
@app.get("/c/{card_id}", response_class=HTMLResponse)
async def scan_landing(request: Request, card_id: str):
    card = card_or_404(card_id)
    # 같은 카드를 다시 열었는지가 애정 지표다. 최초/재방문을 구분해 남긴다.
    try:
        seen = db.count_scans_by_card().get(card_id, 0)
        db.log_event("scan", card_id=card_id, meta={
            "first": seen == 0, "nth": seen + 1,
            "ua": request.headers.get("user-agent", "")[:120],
        })
    except Exception as e:
        logging.warning(f"scan 로그 실패: {e}")
    card.pop("persona", None)
    card.pop("owner_token", None)
    return templates.TemplateResponse("scan.html", {
        "request": request, "card": card, "card_json": json.dumps(card, ensure_ascii=False),
    })


@app.get("/card/{card_id}", response_class=HTMLResponse)
async def printable_card(request: Request, card_id: str):
    card = card_or_404(card_id)
    card["image_path"] = card["photo_path"]   # 인쇄물은 실물 카드와 같아야 한다
    return templates.TemplateResponse("card.html", {
        "request": request, "card": card,
        "qr_url": f"/qr/{card_id}.png",
    })


@app.get("/label/{card_id}", response_class=HTMLResponse)
async def printable_label(request: Request, card_id: str):
    """만들기 화면에서 나온 카드용 60×40mm 라벨. 세로로 디자인하고 인쇄할 때 눕힌다."""
    card = card_or_404(card_id)
    card["image_path"] = card["photo_path"]
    return templates.TemplateResponse("label.html", {
        "request": request, "card": card, "qr_url": f"/qr/{card_id}.png",
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
        try:
            db.log_event("lobby_join", card_id=guest_id, meta={"host": host_id})
        except Exception as e:
            logging.warning(f"lobby_join 로그 실패: {e}")
    return {"ok": True}


@app.get("/api/lobby/{host_id}/invites")
async def lobby_invites(host_id: str):
    """호스트가 대기 중인 참여 신청을 가져간다."""
    _sweep()
    ids = _LOBBIES.get(host_id, {}).get("invites", [])
    return [db.get_card(i) for i in ids if db.get_card(i)]


# ── 측정 대시보드 ──────────────────────────────────────────
def _summarize():
    """소유감(반출)과 애정(재방문)을 따로 볼 수 있게 집계한다."""
    from collections import defaultdict
    events = db.list_events(limit=20000)
    cards = {c["card_id"]: c for c in db.list_cards()}

    by_type = defaultdict(int)
    scans = defaultdict(int)
    calls, rooms = [], []
    first_seen, last_seen = {}, {}
    hours = defaultdict(int)

    for e in events:
        t = e.get("type")
        by_type[t] += 1
        cid, ts = e.get("card_id"), e.get("ts") or ""
        if ts:
            hours[ts[:13]] += 1
        if t == "scan" and cid:
            scans[cid] += 1
            first_seen.setdefault(cid, ts)
            last_seen[cid] = ts
        elif t == "call_end":
            calls.append(e.get("meta", {}))
        elif t == "room_end":
            rooms.append(e.get("meta", {}))

    scanned = len(scans)
    revisited = sum(1 for n in scans.values() if n >= 2)
    # 같은 날 여러 번 연 것과, 날을 넘겨 다시 연 것은 의미가 다르다
    returned_next_day = sum(
        1 for cid in scans
        if first_seen.get(cid, "")[:10] and last_seen.get(cid, "")[:10] > first_seen.get(cid, "")[:10]
    )
    dur = [c.get("seconds", 0) for c in calls if c.get("seconds")]
    rdur = [r.get("seconds", 0) for r in rooms if r.get("seconds")]

    return {
        "cards": {
            "total": len(cards),
            "official": sum(1 for c in cards.values() if c.get("source") == "official"),
            "user": sum(1 for c in cards.values() if c.get("source") == "user"),
            "faceReady": sum(1 for c in cards.values() if c.get("face_status") == "ready"),
            "virtual": sum(1 for c in cards.values() if c.get("avatar_type") == "vrm"),
        },
        "scan": {
            "events": by_type.get("scan", 0),
            "uniqueCards": scanned,
            "revisited": revisited,
            "revisitRate": round(revisited / scanned * 100, 1) if scanned else 0,
            "returnedNextDay": returned_next_day,
        },
        "call": {
            "sessions": len(calls),
            "video": sum(1 for c in calls if c.get("mode") == "video"),
            "voice": sum(1 for c in calls if c.get("mode") == "voice"),
            "avgSeconds": round(sum(dur) / len(dur), 1) if dur else 0,
            "totalMinutes": round(sum(dur) / 60, 1),
            "avgTurns": round(sum(c.get("turns", 0) for c in calls) / len(calls), 1) if calls else 0,
        },
        "room": {
            "sessions": len(rooms),
            "avgSize": round(sum(r.get("size", 0) for r in rooms) / len(rooms), 1) if rooms else 0,
            "avgSeconds": round(sum(rdur) / len(rdur), 1) if rdur else 0,
        },
        "lobbyJoins": by_type.get("lobby_join", 0),
        "issued": by_type.get("card_issued", 0),
        "byType": dict(by_type),
        "hours": dict(sorted(hours.items())),
        "perCard": sorted([
            {
                "cardId": cid,
                "name": cards.get(cid, {}).get("name", "—"),
                "source": cards.get(cid, {}).get("source", "—"),
                "scans": n,
                "first": first_seen.get(cid, ""),
                "last": last_seen.get(cid, ""),
            } for cid, n in scans.items()
        ], key=lambda x: -x["scans"]),
    }


# ── 연구용 ────────────────────────────────────────────────
# docs/연구 설계 — 커스터마이징과 다인 참여.md 참고

CONDITIONS = ["A", "B", "C"]     # A 프리셋 / B 이름 / C 성격까지 직접


@app.get("/api/condition")
async def api_condition():
    """만들기를 시작할 때 조건을 배정한다.

    참가자가 고르게 두면 자기선택 편향이 생기므로 서버가 정한다.
    무작위 대신 가장 적게 배정된 칸을 채워 균형을 맞춘다(전시 표본이 작다).
    """
    counts = {c: 0 for c in CONDITIONS}
    try:
        for e in db.list_events(limit=20000, type="condition_assigned"):
            c = (e.get("meta") or {}).get("depth")
            if c in counts:
                counts[c] += 1
    except Exception as e:
        logging.warning(f"조건 집계 실패: {e}")
    depth = min(CONDITIONS, key=lambda c: counts[c])
    try:
        db.log_event("condition_assigned", meta={"depth": depth, "counts": counts})
    except Exception as e:
        logging.warning(f"condition_assigned 로그 실패: {e}")
    return {"depth": depth, "counts": counts}


@app.post("/api/step")
async def api_step(payload: dict):
    """만들기 단계별 도달 기록. 완주율과 소진 효과를 본다."""
    try:
        db.log_event("create_step", meta={
            "step": str(payload.get("step"))[:32],
            "depth": str(payload.get("depth"))[:4],
            "ms": payload.get("ms"),
        })
    except Exception as e:
        logging.warning(f"create_step 로그 실패: {e}")
    return {"ok": True}


@app.post("/api/survey")
async def api_survey(payload: dict):
    """통화 직후 한 문항. 전시장에서 회수되는 유일한 주관 지표다."""
    try:
        db.log_event("survey", card_id=payload.get("cardId"), meta={
            "q": str(payload.get("q"))[:40],
            "value": payload.get("value"),
            "context": str(payload.get("context"))[:16],
        })
    except Exception as e:
        logging.warning(f"survey 로그 실패: {e}")
    return {"ok": True}


@app.get("/api/stats")
async def api_stats():
    return _summarize()


@app.get("/stats", response_class=HTMLResponse)
async def stats_page(request: Request):
    return templates.TemplateResponse("stats.html", {
        "request": request, "s": _summarize(),
    })
