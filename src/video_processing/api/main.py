from fastapi import FastAPI

from video_processing.api.routes.videos import router as videos_router

app = FastAPI(title="Video Processing API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(videos_router)
