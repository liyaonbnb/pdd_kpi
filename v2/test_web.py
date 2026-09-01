"""Small SPA fallback server for the isolated V2 test build."""

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response
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
    async with httpx.AsyncClient(base_url=API_BASE, timeout=60.0) as client:
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
        # Drop hop-by-hop headers; FastAPI/Starlette will set correct content-length.
        response_headers = dict(response.headers)
        for key in ("content-length", "transfer-encoding", "connection", "content-encoding"):
            response_headers.pop(key, None)
        return Response(content=response.content, status_code=response.status_code, headers=response_headers)


@app.get("/{path:path}")
def serve(path: str = ""):
    candidate = (DIST / path).resolve()
    if candidate.is_relative_to(DIST.resolve()) and candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(DIST / "index.html")

