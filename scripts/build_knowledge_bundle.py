from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = (
    Path.home()
    / "Desktop"
    / "拼多多运营课程"
    / "拼多多运营知识库"
    / "00_统一知识库"
    / "data"
    / "knowledge.db"
)
DEFAULT_OUTPUT = REPO_ROOT / "knowledge" / "data" / "knowledge.db.gz"


def configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_json(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA journal_mode=OFF;
        PRAGMA synchronous=OFF;
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE documents (
            document_id TEXT PRIMARY KEY,
            course_id TEXT NOT NULL,
            course_name TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            source_path TEXT NOT NULL,
            title TEXT NOT NULL,
            topics_json TEXT NOT NULL,
            risk_tags_json TEXT NOT NULL,
            decision_enabled INTEGER NOT NULL
        );
        CREATE TABLE chunks (
            chunk_id TEXT PRIMARY KEY,
            document_id TEXT NOT NULL,
            course_id TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            source_path TEXT NOT NULL,
            title TEXT NOT NULL,
            section TEXT NOT NULL,
            text TEXT NOT NULL,
            topics_json TEXT NOT NULL,
            risk_tags_json TEXT NOT NULL,
            decision_enabled INTEGER NOT NULL
        );
        CREATE TABLE claims (
            knowledge_id TEXT PRIMARY KEY,
            course_id TEXT NOT NULL,
            topic TEXT,
            subtopic TEXT,
            source_path TEXT,
            title TEXT,
            claim_text TEXT,
            screen_fact TEXT,
            applicable_conditions TEXT,
            excluded_conditions TEXT,
            unproven_content TEXT,
            source_status TEXT,
            risk_type TEXT,
            timeliness_risk TEXT,
            decision_reason TEXT,
            rule_snapshot_time TEXT,
            keywords_json TEXT NOT NULL,
            decision_enabled INTEGER NOT NULL
        );
        CREATE INDEX idx_documents_course ON documents(course_id);
        CREATE INDEX idx_chunks_course ON chunks(course_id);
        CREATE INDEX idx_claims_course ON claims(course_id);
        CREATE INDEX idx_claims_decision ON claims(decision_enabled);
        CREATE VIRTUAL TABLE chunk_fts USING fts5(
            chunk_id UNINDEXED,
            title,
            section,
            text,
            topics,
            tokenize='trigram'
        );
        CREATE VIRTUAL TABLE claim_fts USING fts5(
            knowledge_id UNINDEXED,
            topic,
            source_path,
            claim_text,
            conditions,
            keywords,
            tokenize='trigram'
        );
        """
    )


def build_bundle(source: Path, output: Path) -> dict[str, Any]:
    if not source.exists():
        raise FileNotFoundError(f"知识库源文件不存在：{source}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_db = output.parent / "knowledge.bundle.tmp.db"
    if temp_db.exists():
        temp_db.unlink()

    source_connection = sqlite3.connect(source)
    source_connection.row_factory = sqlite3.Row
    target_connection = sqlite3.connect(temp_db)
    try:
        create_schema(target_connection)
        metadata = dict(source_connection.execute("SELECT key, value FROM metadata"))
        metadata.update(
            {
                "bundle_built_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "source_sha256": sha256_file(source),
                "bundle_schema": "pdd-bi-knowledge/v1",
            }
        )
        target_connection.executemany(
            "INSERT INTO metadata(key, value) VALUES (?, ?)", metadata.items()
        )

        documents = source_connection.execute(
            """
            SELECT document_id, course_id, course_name, source_kind, relative_path,
                   title, topics_json, risk_tags_json, decision_enabled
            FROM documents
            """
        ).fetchall()
        target_connection.executemany(
            "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [tuple(row) for row in documents],
        )

        chunks = source_connection.execute(
            """
            SELECT chunk_id, document_id, course_id, source_kind, source_path,
                   title, section, text, topics_json, risk_tags_json, decision_enabled
            FROM chunks
            """
        ).fetchall()
        target_connection.executemany(
            "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [tuple(row) for row in chunks],
        )
        target_connection.executemany(
            "INSERT INTO chunk_fts VALUES (?, ?, ?, ?, ?)",
            [
                (
                    row["chunk_id"],
                    row["title"],
                    row["section"],
                    row["text"],
                    " ".join(parse_json(row["topics_json"], [])),
                )
                for row in chunks
            ],
        )

        source_claims = source_connection.execute(
            "SELECT knowledge_id, course_id, record_json FROM claims"
        ).fetchall()
        claims = []
        for row in source_claims:
            record = parse_json(row["record_json"], {})
            keywords = record.get("keywords") or []
            if not isinstance(keywords, list):
                keywords = [str(keywords)]
            claims.append(
                (
                    row["knowledge_id"],
                    row["course_id"],
                    record.get("topic"),
                    record.get("subtopic"),
                    record.get("source_document"),
                    record.get("lesson_period") or record.get("topic") or row["knowledge_id"],
                    record.get("lecturer_claim"),
                    record.get("screen_or_document_fact"),
                    record.get("applicable_conditions"),
                    record.get("excluded_conditions"),
                    record.get("unproven_content"),
                    record.get("source_status"),
                    record.get("risk_type"),
                    record.get("timeliness_risk"),
                    record.get("decision_reason"),
                    record.get("rule_snapshot_time"),
                    json.dumps(keywords, ensure_ascii=False),
                    int(record.get("decision_enabled") is True),
                )
            )
        target_connection.executemany(
            "INSERT INTO claims VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            claims,
        )
        target_connection.executemany(
            "INSERT INTO claim_fts VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    row[0],
                    " ".join(value for value in (row[2], row[3]) if value),
                    row[4] or "",
                    "\n".join(value for value in (row[6], row[7], row[10]) if value),
                    "\n".join(value for value in (row[8], row[9]) if value),
                    " ".join(parse_json(row[16], [])),
                )
                for row in claims
            ],
        )
        target_connection.commit()
        target_connection.execute("VACUUM")
    finally:
        target_connection.close()
        source_connection.close()

    temp_archive = output.with_suffix(output.suffix + ".tmp")
    with temp_db.open("rb") as source_handle, gzip.open(temp_archive, "wb", compresslevel=9) as target_handle:
        shutil.copyfileobj(source_handle, target_handle, length=1024 * 1024)
    os.replace(temp_archive, output)
    uncompressed_size = temp_db.stat().st_size
    temp_db.unlink()
    return {
        "output": str(output),
        "source": str(source),
        "documents": len(documents),
        "chunks": len(chunks),
        "claims": len(claims),
        "uncompressed_bytes": uncompressed_size,
        "compressed_bytes": output.stat().st_size,
        "archive_sha256": sha256_file(output),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成 pdd_bi_dashboard 可部署知识库压缩包。")
    parser.add_argument(
        "--source",
        type=Path,
        default=Path(os.getenv("PDD_KNOWLEDGE_SOURCE_DB", DEFAULT_SOURCE)),
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


if __name__ == "__main__":
    configure_stdio()
    args = parse_args()
    print(json.dumps(build_bundle(args.source.resolve(), args.output.resolve()), ensure_ascii=False, indent=2))
