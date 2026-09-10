"""Simli API 얇은 래퍼. face_registry(CLI)와 server가 함께 쓴다."""
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
API = "https://api.simli.ai"
KEY = os.getenv("SIMLI_API_KEY", "")


def _headers():
    if not KEY:
        raise RuntimeError("SIMLI_API_KEY가 없습니다 (.env 확인)")
    return {"x-simli-api-key": KEY}


def submit_face(image_bytes, name, filename="face.png"):
    """등록 요청. 성공하면 character_uid를 돌려준다. 완료까지는 최대 8시간."""
    r = requests.post(
        f"{API}/faces/legacy",
        headers=_headers(),
        params={"face_name": name, "characterVersion": "1.5"},
        files={"image": (filename, image_bytes, "image/png")},
        timeout=120,
    )
    r.raise_for_status()
    body = r.json()
    return body.get("character_uid"), body.get("warnings", [])


def generation_status(face_id):
    """processing | completed | failed 등. 문서화되어 있지 않아 원문도 함께 반환."""
    r = requests.get(
        f"{API}/faces/legacy/generation_status",
        headers=_headers(), params={"face_id": face_id}, timeout=30,
    )
    r.raise_for_status()
    body = r.json()
    return body.get("status", "unknown"), body


def active_sessions():
    r = requests.get(f"{API}/ratelimiter/sessions", headers=_headers(), timeout=30)
    r.raise_for_status()
    return r.json().get("currentUsage", 0)


def all_faces():
    r = requests.get(f"{API}/faces", headers=_headers(), timeout=30)
    r.raise_for_status()
    return r.json()
