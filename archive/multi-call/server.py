import logging

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from duo_chat import router as duo_router

logging.basicConfig(level=logging.INFO)

app = FastAPI()
app.include_router(duo_router)


@app.get("/", response_class=HTMLResponse)
async def root():
    with open("duo.html", "r", encoding="utf-8") as f:
        return f.read()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
