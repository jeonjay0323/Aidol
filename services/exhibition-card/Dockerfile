FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DB_BACKEND=firestore

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Cloud Run 은 PORT 를 주입한다. 로컬 실행 시엔 8000.
ENV PORT=8080
CMD exec uvicorn server:app --host 0.0.0.0 --port ${PORT}
