# AI 연습생 음성통화

## 목표

연습생 캐릭터와 실시간 음성 대화가 가능한 인터랙션 시스템 구현

---

## 기술 스택

| 역할 | 선택 | 이유 |
|------|------|------|
| 실시간 대화 AI | Vertex AI — Gemini Live 2.5 Flash Native Audio | GCP 무료 크레딧 사용 가능 |
| STT / TTS | Gemini Live 내장 | 별도 서비스 불필요 |
| 백엔드 | Python FastAPI + WebSocket | 브라우저 ↔ Gemini 프록시 |
| 프론트엔드 | 바닐라 JS + AudioWorklet | 실시간 마이크 캡처 |
| 아바타 립싱크 | Simli (WebRTC P2P) | 사진 한 장으로 실시간 립싱크 |

---

## 아키텍처

```
브라우저 마이크 (AudioWorklet, 16kHz PCM)
    ↓ WebSocket
FastAPI 서버 (server.py)
    ↓ Vertex AI SDK
Gemini Live 2.5 Flash Native Audio
    ↓ 오디오 응답 스트리밍
브라우저 스피커 (AudioContext, 24kHz PCM)
    ↓ 동시 전송 (24kHz → 16kHz 리샘플링)
Simli WebRTC (실시간 립싱크 영상)
```

### 핵심 설계 결정

**클라이언트 VAD (Voice Activity Detection)**
- 브라우저에서 RMS 기반 발화 감지
- 발화 시작 → `activity_start` 신호 전송
- 침묵 1초 지속 → `activity_end` 신호 전송
- Gemini 자동 VAD 비활성화 (`AutomaticActivityDetection(disabled=True)`)

**다중 턴 대화**
- `session.receive()`는 한 턴 후 종료됨 → while 루프로 재호출
- AI 발화 중 마이크 뮤트 (activeSources 카운터)
- Pre-roll 버퍼로 발화 시작 직전 오디오 손실 방지

**오디오 재생**
- 청크 단위 스케줄링 (`nextPlayTime` 기반 seamless 재생)
- AudioContext 자동재생 정책 우회 (버튼 클릭 시점에 생성)

**Simli 립싱크 연동**
- 연습생 선택 시 즉시 Simli WebRTC 연결 → 통화 전부터 얼굴 표시
- P2P 프로토콜: ICE 수집 완료 후 전체 offer 전송 (`enableSFU=true`)
- Gemini 오디오(24kHz) → 16kHz 리샘플링 → 3200샘플 단위 버퍼링 후 전송
- 통화 종료 후 Simli idle 상태 유지 (얼굴 계속 표시)

---

## 연습생 목록

| 이름 | 나이 | 성격 | 목소리 (Gemini) | Simli Face ID |
|------|------|------|----------------|--------------|
| 도윤 | 22살 | 밝고 에너지 넘침 | Puck (활기차고 밝음) | `01f4f536-6612-40f5-b9ba-f635f0b92670` |
| 레오 | 24살 | 차분하고 성숙함 | Charon (차분하고 낮음) | 미등록 |
| 유우키 | 21살 | 장난기 많고 유쾌함 | Fenrir (유쾌하고 에너지) | 미등록 |
| 하늘 | 23살 | 감성적이고 시적 | Orus (안정적이고 감성적) | 미등록 |

> 모든 연습생은 Gemini Prebuilt Voice(남성)로 설정되어 있으며, 성격에 맞는 구어체 프롬프트 적용

---

## 파일 구조

```
services/voice-call/
├── server.py          # FastAPI 백엔드 + Gemini Live + Simli 토큰 발급
├── index.html         # 프론트엔드 UI (Simli WebRTC 포함)
├── pcm-processor.js   # AudioWorklet 마이크 캡처 모듈
└── .env               # SIMLI_API_KEY, (git 제외)
```

### 실행 방법

```bash
cd services/voice-call
pip install fastapi uvicorn google-genai python-dotenv
python3 -m uvicorn server:app --host 0.0.0.0 --port 8000
# → http://localhost:8000
```

---

## 개발 로드맵

| 단계 | 내용 | 상태 |
|------|------|------|
| 1단계 | Gemini Live 음성 대화 프로토타입 | ✅ 완료 |
| 2단계 | 연습생별 성격 프롬프트 | ✅ 완료 |
| 3단계 | Simli 아바타 립싱크 연결 | ✅ 완료 |
| 4단계 | 연습생 성격·목소리 프롬프트 고도화 | ✅ 완료 |
| 5단계 | 나머지 연습생 Face 등록 (레오, 유우키, 하늘) | 🔲 다음 |

---

## 비용

| 항목 | 비용 |
|------|------|
| Vertex AI Gemini Live | GCP 무료 크레딧 사용 중 ($300) |
| Gemini Live 정가 | 오디오 입력 $3 / 출력 $12 per 1M 토큰 |
| 예상 사용량 | 1분 대화 약 $0.05 → 크레딧으로 ~100시간 가능 |
| Simli | 무료 플랜 (월 사용 시간 제한, simli_version: 1) |
