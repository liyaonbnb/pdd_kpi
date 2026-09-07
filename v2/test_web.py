"""Small SPA fallback server for the isolated V2 test build."""

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

try:
    import httpx
except Exception:
    httpx = None

DIST = Path(os.getenv("V2_WEB_DIST", "/opt/pdd_bi_v2_test/frontend/dist"))
API_BASE = os.getenv("V2_API_INTERNAL_URL", "http://127.0.0.1:18000")

_HOP_BY_HOP = {"host", "content-length", "connection", "transfer-encoding", "keep-alive", "upgrade"}

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
        return JSONResponse({"detail": "httpx not installed"}, status_code=503)
    method = request.method
    url = f"/api/{path}"
    if request.query_params:
        url = f"{url}?{request.query_params}"
    headers = {key: value for key, value in request.headers.items() if key.lower() not in _HOP_BY_HOP}
    body = await request.body()
    async with httpx.AsyncClient(base_url=API_BASE, timeout=60.0) as client:
        try:
            response = await client.request(method, url, headers=headers, content=body)
        except httpx.NetworkError:
            return JSONResponse({"detail": "V2 API service unreachable"}, status_code=503)
        except httpx.TimeoutException:
            return JSONResponse({"detail": "V2 API request timed out"}, status_code=504)
        out_headers = {key: value for key, value in response.headers.items() if key.lower() not in _HOP_BY_HOP}
        content = await response.aread()
    return Response(content=content, status_code=response.status_code, headers=out_headers)


@app.get("/{path:path}")
def serve(path: str = ""):
    candidate = (DIST / path).resolve()
    if candidate.is_relative_to(DIST.resolve()) and candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(DIST / "index.html")
