# Exhibition Card — 전시용 피지컬 카드 시스템

카드를 스캔하면 그 아이돌과 영상통화가 시작된다.
다른 카드를 초대하면 여럿이 함께 대화한다.

**배포** Cloud Run `aidol-card` (asia-northeast3) · Firestore

## 왜 이렇게 만들었나

카드 발급은 즉시 이뤄져야 하고, Simli 얼굴 등록은 **최대 8시간**이 걸린다.
이 간격을 `face_status`로 표현하는 것이 설계의 뼈대다.

| face_status | 스캔 화면 | 통화 |
|---|---|---|
| `ready` | "지금 영상통화할 수 있어요" | 영상 + 음성 |
| `processing` | "얼굴을 만드는 중" | 음성만 |
| `failed` / `none` | "목소리로 통화할 수 있어요" | 음성만 |

등록이 실패해도 카드는 이미 관람객 손에 있고 대화는 된다.

## 구조

```
server.py          FastAPI · 라우팅 · Simli 프록시
db.py              DB_BACKEND 로 Firestore / SQLite 선택
  db_firestore.py    운영 (Cloud Run)
  db_sqlite.py       로컬 개발
call.py            1:1 통화 WebSocket
room.py            멀티콜 · 발언권 중재
simli.py           Simli API 래퍼
worker.py          얼굴 등록 상태 폴링
face_registry.py   얼굴 일괄 등록 CLI
make_qr.py         카드 QR 생성
templates/         scan · card · admin
static/            통화 클라이언트 · jsQR
```

## 통화

**1:1** — Gemini 자동 발화감지를 끄고 브라우저가 RMS로 판단한다.
임계값 0.02 · 침묵 1초 · 최소 15청크 · preroll 5청크(첫 음절 잘림 방지).
응답 오디오는 스피커와 Simli로 동시에 흐른다(24kHz → 16kHz 리샘플).

**멀티콜** — 여럿이 동시에 말하면 겹치므로 서버가 매 턴 화자 하나를 정한다.

```
사람 발화 → 선택된 아이돌에게만 음성 → 응답
                                    ├→ 나머지에게 텍스트 주입 (turn_complete=False, 응답 안 함)
                                    └→ 한 명에게 릴레이 (turn_complete=True, 받아침)
```

`MAX_RELAYS`(기본 2)만큼 아이돌끼리 주고받은 뒤 사람을 기다린다.
화면에서 얼굴을 탭하면 그 아이돌이 답한다.

## 초대 경로

관람객 기기를 통제할 수 없어 넷을 열어뒀다. 모두 같은 로비로 모인다.

| 경로 | 기기 |
|---|---|
| QR 스캔 (`BarcodeDetector`, 없으면 `jsQR`) | 전 기기 |
| NFC 탭 (`NDEFReader`) | 안드로이드 Chrome |
| 카드 탭 → 페이지 열림 → 참여 배너 | **전 기기 (iOS 포함)** |
| 로비에서 직접 선택 | 전 기기 |

iOS는 Web NFC와 BarcodeDetector가 모두 없다. QR은 jsQR로, NFC는
"카드를 탭하면 OS가 페이지를 연다"는 성질을 이용해 우회했다.

## API

| | |
|---|---|
| `POST /api/cards` | 카드 발급. 이미지 동봉 시 얼굴 등록까지 |
| `GET /api/cards/{id}/call` | 통화 설정 — mode · persona · voice · faceId |
| `GET /c/{id}` | 스캔 랜딩 |
| `GET /card/{id}` · `/qr/{id}.png` | 인쇄용 카드 · QR |
| `GET /admin` | 카드 관리 · NFC 쓰기 |
| `WS /ws/call/{id}` · `WS /ws/room` | 1:1 · 멀티콜 |
| `POST /api/lobby/{id}/open` 외 | 로비 · 원격 참여 |

## 실행

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
cp .env.example .env      # SIMLI_API_KEY 등을 채운다
./.venv/bin/python -m uvicorn server:app --port 8000

# 얼굴 등록 (faces/ 에 정면 이미지를 넣고)
./.venv/bin/python face_registry.py register
./.venv/bin/python worker.py 30      # 상태를 DB 에 반영
```

폰에서 마이크를 쓰려면 **HTTPS가 필수**다(`getUserMedia`는 secure context 전용).
로컬 IP로는 통화가 되지 않는다.

## 얼굴 이미지 요건

정면 · 손이 얼굴을 가리지 않을 것 · **1024×1024 정사각형**.
그 외 비율은 정사각으로 크롭되고, 512 배수가 아니면 스케일링 손실이 생긴다.

## 알려진 제약

- **인쇄 QR 밀도** — Cloud Run 기본 주소(66자)는 버전 5·37모듈이다.
  카드의 QR을 17mm로 잡아 모듈당 0.459mm를 확보했다(권장 0.4mm).
  짧은 커스텀 도메인을 쓰면 14mm로 줄일 수 있다.
- **`BASE_URL`은 반드시 환경변수로 고정해야 한다** — 없으면 요청 헤더로 주소를 만드는데,
  Cloud Run은 프록시 뒤라 스킴이 `http`로 잡히고 접근 경로에 따라 QR 내용이 달라진다.
  인쇄물이므로 치명적이다.
- **legacy 얼굴 API는 deprecated** — Trinity가 현행이지만 동시 세션 때문에 legacy를 쓴다.
- **로비는 "가장 최근 하나"** — 전시 부스가 하나라는 전제다.
- **통화 중 초대 불가** — 참가자는 시작 전에 확정된다.
