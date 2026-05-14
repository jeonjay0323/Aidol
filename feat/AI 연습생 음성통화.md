# AI 연습생 음성통화 기획안

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
| 아바타 | 추후 D-ID / Simli 추가 예정 | 모듈식 설계 |

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

---

## 연습생 목록

| 이름 | Buppy Companion ID |
|------|-------------------|
| 양우진 | cc426433-4ba4-45c3-9b12-60ebc43e27cd |
| 황정우 | 2746e567-8a38-4c95-863a-3b3daccdf57c |
| 노담 | aa20ecf3-4784-4667-a333-6b056ec6068a |
| 남지안 | 12842208-2240-4618-b96b-2974af3f8d78 |
| 염윤호 | 73a38b21-7a8c-4246-8d37-d25b1a787068 |
| 김수호 | 99a736dd-e725-454f-9dbd-e74c99f83a56 |
| 허우진 | 9b0fb290-5b4c-4af1-aab2-c012700d46cc |
| 장준혁 | 003b0d18-457a-4575-8050-25da26f75e2f |

---

## 프로토타입 파일 구조

```
prototype/
├── server.py          # FastAPI 백엔드 + Gemini Live 연동
├── index.html         # 프론트엔드 UI
├── pcm-processor.js   # AudioWorklet 마이크 캡처 모듈
└── .env               # GEMINI_API_KEY (git 제외)
```

### 실행 방법

```bash
cd prototype
pip install fastapi uvicorn google-genai python-dotenv
python server.py
# → http://localhost:8000
```

---

## 개발 로드맵

| 단계 | 내용 | 상태 |
|------|------|------|
| 1단계 | Gemini Live 음성 대화 프로토타입 | ✅ 완료 |
| 2단계 | 연습생별 성격 프롬프트 | 🔲 다음 |
| 3단계 | 아바타 립싱크 연결 | 🔲 추후 |

---

## 비용

| 항목 | 비용 |
|------|------|
| Vertex AI Gemini Live | GCP 무료 크레딧 사용 중 |
| 오디오 정가 | 입력 $2.10 / 출력 $8.50 per 1M 토큰 |
| 아바타 (추후) | D-ID 무료 티어 or Simli 유료 검토 |
