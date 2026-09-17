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
├── services/                구현
│   └── exhibition-card/     전시용 피지컬 카드 · 통화 · 멀티콜
├── tools/                   제작 도구
│   └── image-generator/     아이돌 이미지 생성
└── archive/                 대체된 프로토타입
    ├── solo-call/           1:1 통화 원형
    └── multi-call/          대사 사전생성 방식
```

## 서비스

### `exhibition-card` — 전시용 피지컬 카드
왜 카드인지, 무엇을 확인하려는 실험인지는
[실험 배경 문서](docs/실험%20배경%20—%20다인%20참여형%20컴패니언.md)에 정리돼 있다.

카드를 스캔하면 그 아이돌과 영상통화가 시작된다.
다른 카드를 초대하면 여럿이 함께 대화한다. Cloud Run + Firestore 로 배포되어 있다.
→ [상세 문서](services/exhibition-card/README.md)

### `tools/image-generator` — 아이돌 이미지 생성
카드에 들어갈 인물 이미지를 만든다. Simli 얼굴 등록에는 정면 · 1024×1024 정사각형이 필요하다.

### `archive/` — 대체된 프로토타입
`solo-call`(Gemini Live + Simli 1:1 통화)의 구조는 exhibition-card 로 흡수됐다.
`multi-call`은 대사를 미리 만들어 재생하는 다른 기능이라 재사용하지 않았다.
개발 과정을 보여주는 자료로 남겨뒀다.
→ [archive/README.md](archive/README.md)

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
