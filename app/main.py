from fastapi import FastAPI

app = FastAPI(title="Mission Control: Go/No-Go Launch Console")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
