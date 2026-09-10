# 카드 서버

전시용 아이돌 카드. 카드를 스캔하면 캐릭터 페이지가 열리고 영상통화로 이어진다.
카드는 즉시 발급되고 얼굴은 최대 8시간 뒤에 붙는다 — 그 간격을 `face_status`로 표현하고,
스캔 시 상태에 따라 화면을 분기한다.

## 배포

Cloud Run (서울 리전). **인쇄물 QR이 가리키는 주소라 도메인이 바뀌면 안 된다.**

```
https://aidol-card-294218538342.asia-northeast3.run.app
```

```bash
gcloud run deploy aidol-card \
  --source . --project=aidol-505503 --region=asia-northeast3 \
  --allow-unauthenticated --port=8080 --memory=1Gi --timeout=3600 \
  --set-env-vars="DB_BACKEND=firestore,GCP_PROJECT=aidol-505503,GCP_LOCATION=us-central1,SIMLI_API_KEY=..."
```

## 저장소

`db.py`가 `DB_BACKEND` 환경변수로 분기한다.

| 값 | 백엔드 | 쓰는 곳 |
|---|---|---|
| `sqlite` (기본) | `cards.db` 파일 | 맥에서 개발할 때 |
| `firestore` | Firestore `cards` 컬렉션 | Cloud Run |

**Cloud Run 은 컨테이너 파일시스템이 휘발성이라 SQLite 를 쓸 수 없다.**
맥에서 도는 얼굴 워커도 `DB_BACKEND=firestore`로 띄우면 같은 저장소를 본다.

## 환경변수

| | |
|---|---|
| `DB_BACKEND` | `sqlite` \| `firestore` |
| `GCP_PROJECT` | 기본 `aidol-505503` |
| `GCP_LOCATION` | Vertex AI 리전, 기본 `us-central1` |
| `SIMLI_API_KEY` | 영상통화 아바타. **커밋 금지** — 로컬은 `.env`, 배포는 `--set-env-vars` |
| `BASE_URL` | 비우면 요청 host 를 그대로 쓴다 |

## QR

```bash
python3 make_qr.py              # DB 의 모든 카드
python3 make_qr.py G6CNSAAA     # 특정 카드만
python3 make_qr.py --base http://localhost:8000   # 로컬 테스트
```

주소는 `make_qr.py`의 `BASE_URL` 상수에 박혀 있다. 로컬 IP 를 잡던 이전 방식은
네트워크가 바뀔 때마다 QR 이 죽어서 폐기했다.

**끝 슬래시를 붙이지 않는다** — `/c/{id}/` 는 307 리다이렉트 후 404 가 난다.

## 로컬 실행

```bash
pip install -r requirements.txt
uvicorn server:app --reload --port 8000
```

## 저장소에 없는 것

- `.env` — 키가 들어 있어 커밋하지 않는다
- `cards.db` — 로컬 SQLite. 운영 데이터는 Firestore 에 있다
- `static/faces/*.png` — 생성된 카드 얼굴. 배포 시 로컬 폴더에서 함께 올라간다
- `faces/` — 얼굴 워커 스테이징
