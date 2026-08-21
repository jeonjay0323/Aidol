# Lukids

> AI 아이돌과 1:1로 소통하는 서비스 — 경희대학교 졸업스튜디오3 개인작

프롬프트로 아이돌을 만들고, 영상통화로 대화하고, 관계를 쌓는다.
기존 캐릭터챗이 1:1 텍스트에 머무는 것과 달리, **얼굴을 보고 목소리로 대화하는 것**을 중심에 둔다.

> "실제 아이돌은 나를 모르지만, 이 아이돌은 나를 안다"

선택하는 경험이 아니라 **선택받는** 경험. AI 아이돌이 먼저 통화를 걸어온다.

## 구조

```
Aidol/
├── docs/                    기획 문서
│   ├── 프로젝트 기획안.md
│   └── 프로젝트 진행 상황.md
├── feat/                    기능 명세
│   ├── AI 개인 영상 통화.md
│   ├── AI 다자간 통화.md
│   └── 유저 취향 분석.md
└── services/                구현
    ├── solo-call/           1:1 영상통화
    ├── multi-call/          다자간 통화
    └── exhibition-card/     전시용 피지컬 카드
```

## 서비스

### `solo-call` — 1:1 영상통화
Gemini Live 2.5 Flash Native Audio + Simli WebRTC 실시간 립싱크.
FastAPI / WebSocket, AudioWorklet 16kHz, 클라이언트 VAD, 다중 턴.

### `multi-call` — 다자간 통화
Gemini 2.5 Flash로 대사 일괄 생성 후 Gemini TTS 1줄 선행 파이프라인 + ACK 동기화, 분할 화면.
Simli 무료 플랜의 1연결 제한으로 다자간 립싱크는 미적용 상태.

### `exhibition-card` — 전시용 피지컬 카드
아이돌 카드를 스캔하면 그 아이돌과 영상통화가 시작된다.
다른 카드를 스캔하면 그 아이돌과 **카드 주인**을 멀티콜에 부를 수 있다.
→ [상세 문서](services/exhibition-card/README.md)

## 실행

각 서비스 디렉토리의 README 또는 `config.py`를 참고한다.
API 키는 `.env`로 관리하며 저장소에 포함하지 않는다.

| 환경변수 | 용도 |
|---|---|
| `SIMLI_API_KEY`, `SIMLI_FACE_ID` | 아바타 얼굴 · 립싱크 |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` | TTS 음성 |
| `GOOGLE_CLOUD_PROJECT`, `VERTEX_LOCATION` | Gemini (Vertex AI) |

## 관련 자산

- **브랜드 가이드라인** — LUKI2DS 브랜드북 (별도 저장소)
- **talking-face** — Pipecat 기반 영상통화 봇 프로토타입 (별도 로컬 프로젝트).
  `exhibition-card`의 통화 엔진 후보 중 하나
