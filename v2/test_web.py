"""Small SPA fallback server for the isolated V2 test build."""

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

try:
    import httpx
except Exception:
    httpx = None

DIST = Path(os.getenv("V2_WEB_DIST", "/opt/pdd_bi_v2_test/frontend/dist"))
API_BASE = os.getenv("V2_API_INTERNAL_URL", "http://127.0.0.1:18000")

app = FastAPI(title="PDD BI V2 Test Web")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy_api(request: Request, path: str):
    """Proxy API requests to the V2 API service."""
    if httpx is None:
        from starlette.responses import JSONResponse
        return JSONResponse({"detail": "httpx not installed"}, status_code=503)
    client = httpx.AsyncClient(base_url=API_BASE, timeout=60.0)
    try:
        method = request.method
        url = f"/api/{path}"
        if request.query_params:
            url = f"{url}?{request.query_params}"
        headers = {}
        for key, value in request.headers.items():
            if key.lower() in {"host", "content-length", "connection"}:
                continue
            headers[key] = value
        body = await request.body()
        response = await client.request(method, url, headers=headers, content=body)
        return StreamingResponse(response.aiter_raw(), status_code=response.status_code, headers=dict(response.headers))
    finally:
        await client.aclose()


@app.get("/{path:path}")
def serve(path: str = ""):
    candidate = (DIST / path).resolve()
    if candidate.is_relative_to(DIST.resolve()) and candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(DIST / "index.html")
