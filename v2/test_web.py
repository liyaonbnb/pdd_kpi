"""Small SPA fallback server for the isolated V2 test build."""

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse


DIST = Path(os.getenv("V2_WEB_DIST", "/opt/pdd_bi_v2_test/frontend/dist"))
app = FastAPI(title="PDD BI V2 Test Web")


@app.get("/{path:path}")
def serve(path: str = ""):
    candidate = (DIST / path).resolve()
    if candidate.is_relative_to(DIST.resolve()) and candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(DIST / "index.html")
