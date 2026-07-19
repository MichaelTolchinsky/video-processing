from fastapi import FastAPI

from video_processing.api.routes.health import router as health_router
from video_processing.api.routes.videos import router as videos_router

app = FastAPI(title="Video Processing API")

app.include_router(health_router)
app.include_router(videos_router)
