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

## 버추얼 카드 · 꾸미기

`avatar_type=vrm` 카드는 Simli 대신 브라우저가 VRM 모델을 직접 그린다(`vrm-avatar.js`).
응답 음량으로 입을 움직이고, 눈 깜빡임 · 숨쉬기 · 고개 흔들림을 준다.

```bash
./.venv/bin/python tools/virtual_card.py haneul 하늘.vrm 썸네일.png
```

카드 화면의 꾸미기에서 주인이 바꾼 값은 `custom` 필드에 저장된다.

| 항목 | 반영 위치 |
|---|---|
| 머리 · 눈 · 상의 · 하의 · 신발 색 | 브라우저가 텍스처를 다시 칠한다 (VRoid 재질 이름 기준) |
| 말투 · 호칭 · 한 줄 설정 | 서버가 통화 페르소나 뒤에 붙인다 (1:1 · 멀티콜 공통) |

## 내 아이돌 만들기

카드 화면의 "내 아이돌 만들기"에서 실물 · 버추얼을 고르고, 조합과 직접 쓴 프롬프트로
사진을 생성해 바로 인쇄한다. Simli 등록은 하지 않는다 — 만든 카드는 음성 통화로 시작한다.

| | 고르는 것 | 프롬프트 |
|---|---|---|
| 실물 | 일상(분위기 6) · 에픽(이종족 11) | `app/gen/idol.py` — ~/claude/idol-photos 아이돌 생성기(female_idol · male_idol) 사본 |
| 버추얼 | 분위기 5 · 머리색 6 | `app/imagegen.py` 애니 일러스트 |

`POST /api/generate` 가 JPEG 을 돌려주고(저장 안 함), 고른 한 장을 `POST /api/cards`
에 `register_face=false` 로 실어 발급한다. 사진은 Firestore `thumbs` 에 들어가서
인스턴스가 재시작돼도 `/label/{id}?print=1` 로 다시 인쇄할 수 있다.
라벨 용지는 60×40mm 다. 사진은 세로 2:3 으로 뽑고 라벨도 40×60 세로로 그린 뒤, 인쇄할 때만 90° 눕힌다.
연구 조건 A 는 직접 쓰는 칸을 숨긴다(고르기만).

## 사이트 — 중간 보고용 프로토타입

카드 화면(`/c/{id}`) 바깥에 다섯 페이지를 두고 상단 메뉴로 묶었다.

| 주소 | 페이지 | 내용 |
|---|---|---|
| `/` | 소개 | 루키즈 소개 · 네 기능 · 공식 라인업 · 최근 만든 아이돌 |
| `/make` | 01 제작 | 카드 화면의 만들기와 같은 흐름. 모든 칸을 연다(조건 C, `?depth=A` 로 바꿀 수 있다) |
| `/print` | 02 인쇄 | 이 기기에서 만든 카드(localStorage `lukids.mine`)의 라벨 미리보기 · 인쇄, 번호로 찾기 |
| `/gallery` | 03 전시 | `source=user` 카드 전체. 실물 · 버추얼 필터, 20초마다 새 카드를 받는다 |
| `/call` | 04 통화 | 공식 아이돌 5명. `main.py` 의 `LINEUP` 이 이름으로 카드를 찾는다 |

만들기 마크업과 스크립트는 `_create_screens.html` · `static/create.js` 로 빼서 두 곳이 같이 쓴다.
카드 화면의 스타일은 `static/scan.css`, 사이트 틀은 `_site.html` · `static/site.css`.

공식 아이돌 중 도하 · 린은 `tools/seed_lineup.py` 로 발급한다(사진 생성 → 공식 카드 → Simli 등록).
사진은 로컬 `app/static/faces/` 에도 남으니 발급한 뒤 다시 배포해야 사진이 유지된다.

```bash
./.venv/bin/python tools/seed_lineup.py https://aidol-card-938904157102.asia-northeast3.run.app
```

### 표정 바뀌는 통화 — 공식 아이돌

`app/static/expr/<slug>/` 에 기본 사진(base)과 표정 5장(laugh · surprised · thinking · shy · sad)을 두면
그 공식 아이돌은 모든 화면에서 기본 사진으로 보이고, 통화는 큰 사진의 음성 통화가 된다. 단 Simli 얼굴이 준비된 카드(하루 · 시온)는 영상 통화가 우선이고, VRM(하늘)은 표정 세트가 대신한다.
Gemini Live 의 출력 자막(`output_audio_transcription`)을 브라우저로 보내고, 아이돌이 하는 말에
"ㅋㅋ/신났" → 웃음, "헐/진짜?" → 놀람 같은 낱말이 나오면 그 표정으로 바꾼다. 말을 마치면 2.5초 뒤 기본으로.
사진은 배포에 실리는 파일이라 운영 DB 는 그대로다. 표정 사진은 `tools/make_expressions.py <slug>` —
기본 사진을 기준으로 얼굴만 바꿔 그린다. 하늘은 3D 대신 2D 일러스트로 바뀌었다(기존 VRM 카드 KACJE0ZS 그대로).

### 시연 모드 — `/demo`

아이패드 시연용 첫 화면. "아이돌 만들기"와 "아이돌과 통화하기" 두 개만 크게 보인다.
여기서 들어가면 sessionStorage `lukids.demo` 가 켜져 상단 메뉴 대신 "처음으로"만 남고,
카드 화면의 멀티콜 · 만들기 · 통화 뒤 설문 · 열린 통화 안내가 숨는다.
만들기는 발급 → 인쇄 → 통화하기 순서로 흐른다(발급 뒤 아이돌이 먼저 거는 전화는 2026-10-07 껐다).
라벨 페이지에는 인쇄 창이 자동으로 안 뜨는 기기를 위해 인쇄 · 닫기 버튼이 있다.

### 아이돌이 먼저 거는 전화

카드를 발급하고 4초 뒤 방금 만든 아이돌에게서 전화가 온다(`static/ring.js`). 받으면
`/c/{id}?answer=1` 로 넘어가 곧장 통화하고, 브라우저가 소리를 막으면 화면을 한 번 누르게 한다.
`/c/{id}?ring=1` 로 열면 아무 카드나 먼저 전화를 건다(전시 시연용).
거절 · 부재중 · 받기는 `create_step` 이벤트(`ring`, `ring-answer`, `ring-declined`, `ring-missed`)로 남는다.
음성 통화(영상이 없는 카드)는 전화 앱 화면으로 바뀐다 — 이름 · 통화 시간 · 사진 둘레 물결과 파형
(아이돌이 말할 때 움직인다) · 스피커 · 음소거 · 끊기. 브라우저는 수화기/스피커를 고를 수 없어서
스피커 버튼은 소리 크게(기본)와 작게(30%)를 오간다. Simli · VRM 영상 통화 화면은 그대로다.

### 라벨 프린터(Aiyin 앱)

블루투스 라벨 프린터는 AirPrint 가 안 돼서 브라우저 인쇄 창으로는 못 뽑는다.
`GET /label/{id}.png` 가 라벨을 300dpi 이미지(용지 방향 60×40mm, 709×472)로 그리고(`app/label_png.py`),
라벨 페이지의 "Aiyin 앱으로 보내기"가 아이패드 공유 시트로 넘긴다. 흑백 감열 프린터면 `?mono=1`(디더링).

### 블루투스로 바로 인쇄 (Web Bluetooth)

아이패드 사파리는 Web Bluetooth 가 없어서 Bluefy 앱에서 연다. `static/bt-print.js` 가 프린터를 고르고
`/label/{id}.png?mono=1&dpi=203`(480×320, 60×40mm)을 1비트 비트맵으로 바꿔 TSPL(기본) 또는 ESC/POS 로 보낸다.
Aiyin 계열은 ISSC 투명 UART(`49535343-fe7d-…`)로 받는다. 기종마다 달라서 `/printer` 에서
언어 · 해상도 · 크기 · 간격 · 방향 · 진하기 · 흑백 뒤집기를 바꿔 가며 시험 인쇄하고, 맞춘 값은 localStorage 에 남아
라벨 화면의 "블루투스로 바로 인쇄"가 그대로 쓴다. 실제 프린터로는 아직 확인하지 못했다(2026-10-07).

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

## 측정

실험 지표를 남기기 위해 행동 로그를 쌓는다. 자세한 배경은
[실험 배경 문서](../../docs/실험%20배경%20—%20다인%20참여형%20컴패니언.md) 참고.

| 이벤트 | 언제 | 무엇을 본다 |
|---|---|---|
| `scan` | `/c/{id}` 열람 | 소유·애정 — `first`/`nth` 로 재방문 판별 |
| `card_issued` | 카드 발급 | 발급량 |
| `call_start` · `call_end` | 1:1 통화 | 몰입 — 지속 시간·턴 수 |
| `room_start` · `room_end` | 멀티콜 | 다인 노출 — 인원·릴레이 수 |
| `lobby_join` | 원격 참여 신청 | 확장 의지 |

로그 실패가 본 기능을 막지 않도록 모든 기록은 `try/except` 로 감쌌다.

**대시보드** `GET /stats` — 재방문율을 중심 지표로 놓고, 카드별 스캔 이력을 표로 본다.
`GET /api/stats` 는 같은 집계를 JSON 으로 돌려준다.

소유감과 애정을 한 지표로 합치지 않는다. 카드는 가져갔는데 다시 안 여는 사람과,
두고 갔는데 집에서 계속 통화하는 사람은 다른 이야기다.

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
