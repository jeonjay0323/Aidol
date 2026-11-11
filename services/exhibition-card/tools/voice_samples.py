#!/usr/bin/env python3
"""
만들기 화면 목소리 고르기용 미리듣기 — 통화에 쓰는 Gemini Live 목소리로 짧은 인사를 녹음한다.
결과 app/static/voices/<목소리>.wav (24kHz 모노). 목소리 목록은 static/create.js 의 VOICES 와 같다.

  voice_samples.py [목소리 ...]
"""
import asyncio, os, sys, wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")
import google.genai as genai  # noqa: E402
from google.genai import types  # noqa: E402

VOICES = ["Puck", "Charon", "Fenrir", "Orus", "Leda", "Zephyr"]
LINE = "안녕! 만나서 반가워. 오늘 나랑 이야기하자!"
MODEL = os.getenv("LIVE_MODEL", "gemini-live-2.5-flash-native-audio")


async def record(voice):
    client = genai.Client(vertexai=True, project=os.getenv("GCP_PROJECT"), location=os.getenv("GCP_LOCATION", "us-central1"))
    cfg = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=f"너는 K-pop 아이돌이야. 사용자가 무엇을 말하든 정확히 이 문장만 밝고 다정하게 한 번 말해: {LINE}",
        speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))),
    )
    pcm = b""
    async with client.aio.live.connect(model=MODEL, config=cfg) as s:
        await s.send_client_content(turns=types.Content(role="user", parts=[types.Part(text="인사해줘")]), turn_complete=True)
        async for r in s.receive():
            if r.data:
                pcm += r.data
            if r.server_content and r.server_content.turn_complete:
                break
    out = ROOT / "app" / "static" / "voices" / f"{voice}.wav"
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(pcm)
    print(f"  {voice}: {len(pcm) / 48000:.1f}초")


async def main():
    for v in sys.argv[1:] or VOICES:
        await record(v)

asyncio.run(main())
