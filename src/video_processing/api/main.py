from fastapi import FastAPI

app = FastAPI(title="Video Processing API")

@app.get("/health")
def health() -> dict[str,str]:
    return {"status": "ok"}