import asyncio
import base64
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import google.genai as genai
from google.genai import types

from config import GCP_PROJECT, GCP_LOCATION, TTS_MODEL, DIALOGUE_MODEL, TRAINEE_VOICES, TRAINEES

log = logging.getLogger("trainee")
router = APIRouter()


async def _tts(client, char: str, text: str) -> str:
    voice = TRAINEE_VOICES.get(char, "Puck")
    resp  = await client.aio.models.generate_content(
        model=TTS_MODEL,
        contents=text,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                )
            )
        )
    )
    raw = resp.candidates[0].content.parts[0].inline_data.data
    return base64.b64encode(raw).decode() if isinstance(raw, bytes) else raw


@router.websocket("/ws/duo")
async def duo_chat(websocket: WebSocket):
    await websocket.accept()
    log.info("다자간 통화 연결")

    try:
        cfg       = json.loads(await websocket.receive_text())
        char_a    = cfg.get("char_a", "도윤")
        char_b    = cfg.get("char_b", "레오")
        situation = cfg.get("situation", "연습 끝나고 숙소에서 샤워 먼저 하겠다고 서로 안 비켜주는 상황")
        turns     = cfg.get("turns", 24)

        client = genai.Client(vertexai=True, project=GCP_PROJECT, location=GCP_LOCATION)
        await websocket.send_text(json.dumps({"type": "generating"}))

        # 1. 대화 텍스트 일괄 생성
        prompt = (
            f"{char_a} 소개: {TRAINEES.get(char_a, '')}\n"
            f"{char_b} 소개: {TRAINEES.get(char_b, '')}\n\n"
            f"상황: {situation}\n\n"
            f"두 사람이 티격태격하는 대화를 {turns}줄 써줘.\n\n"
            f"말투 규칙 (반드시 지킬 것):\n"
            f"- 2024년 한국 10~20대 남자애들이 실제로 쓰는 말투\n"
            f"- '야', '아', '어', '진짜', '개-', '레알', '헐', '뭐야' 같은 구어체 감탄사로 문장 시작\n"
            f"- 문장 끝에 '~거든?', '~잖아', '~냐고', '~라고' 등 친구 사이 반말체\n"
            f"- 한 대사는 1~2문장, 최대 20자 이내로 짧게\n"
            f"- 이모지나 ㅋㅋ 금지, 소리 나는 그대로만\n"
            f"- 말 시작에 '아', '야', '어', '음' 같은 자연스러운 시작 습관 포함\n"
            f"- 아이돌 연습생끼리 쓸 법한 표현 (연습, 컨셉, 무대, 체력 등)\n\n"
            f"아래 형식만 사용 (다른 텍스트 없이):\n"
            f"{char_a}: [대사]\n{char_b}: [대사]"
        )
        log.info("대화 텍스트 생성 중...")
        resp  = await client.aio.models.generate_content(model=DIALOGUE_MODEL, contents=prompt)
        lines = []
        for line in resp.text.strip().split('\n'):
            line = line.strip()
            if line.startswith(f"{char_a}:"):
                lines.append({"character": char_a, "text": line[len(char_a)+1:].strip()})
            elif line.startswith(f"{char_b}:"):
                lines.append({"character": char_b, "text": line[len(char_b)+1:].strip()})
        log.info(f"대화 {len(lines)}줄 생성 완료")

        await websocket.send_text(json.dumps({"type": "start"}))

        # 2. TTS 파이프라인: 현재 줄 재생 중 다음 줄 TTS 미리 생성
        tts_task = asyncio.create_task(_tts(client, lines[0]["character"], lines[0]["text"]))

        for i, line in enumerate(lines):
            audio = await tts_task
            log.info(f"[{i+1}/{len(lines)}] {line['character']}: {line['text']}")

            if i + 1 < len(lines):
                tts_task = asyncio.create_task(
                    _tts(client, lines[i+1]["character"], lines[i+1]["text"])
                )

            await websocket.send_text(json.dumps({
                "type": "line",
                "character": line["character"],
                "text": line["text"],
                "audio": audio,
            }))

            ack = json.loads(await websocket.receive_text())
            if ack.get("type") == "stop":
                if i + 1 < len(lines):
                    tts_task.cancel()
                break

        await websocket.send_text(json.dumps({"type": "end"}))
        log.info("다자간 통화 완료")

    except WebSocketDisconnect:
        log.info("클라이언트 연결 종료")
    except Exception as e:
        log.error(f"다자간 통화 오류: {e}")
        try:
            await websocket.send_text(json.dumps({"type": "error", "data": str(e)}))
        except Exception:
            pass
