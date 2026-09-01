from __future__ import annotations

import gzip
import json
import os
import re
import shutil
import sqlite3
import threading
from collections import Counter
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from api_client import call_llm
from config_manager import get_config_defaults


ROOT = Path(__file__).resolve().parent
BUNDLE_ARCHIVE = ROOT / "knowledge" / "data" / "knowledge.db.gz"
DEFAULT_RUNTIME_DB = ROOT / "data" / "knowledge" / "knowledge.db"
NO_VERIFIED_KNOWLEDGE = (
    "当前知识库没有已验证的可执行观点，需要结合当前商家后台、官方规则和店铺真实数据复核。"
)
ASSISTANT_MIN_TIMEOUT_SECONDS = 180
_DB_LOCK = threading.Lock()


def _runtime_db_path() -> Path:
    configured = os.getenv("PDD_KNOWLEDGE_DB")
    return Path(configured).expanduser().resolve() if configured else DEFAULT_RUNTIME_DB


def ensure_knowledge_database() -> Path:
    target = _runtime_db_path()
    if os.getenv("PDD_KNOWLEDGE_DB"):
        if not target.exists():
            raise FileNotFoundError(f"PDD_KNOWLEDGE_DB 指向的文件不存在：{target}")
        return target
    if not BUNDLE_ARCHIVE.exists():
        raise FileNotFoundError("知识库部署包不存在，请先运行 scripts/build_knowledge_bundle.py")
    with _DB_LOCK:
        if target.exists() and target.stat().st_mtime >= BUNDLE_ARCHIVE.stat().st_mtime:
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(".tmp")
        with gzip.open(BUNDLE_ARCHIVE, "rb") as source, temp.open("wb") as destination:
            shutil.copyfileobj(source, destination, length=1024 * 1024)
        os.replace(temp, target)
    return target


def _connect() -> sqlite3.Connection:
    path = ensure_knowledge_database()
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _parse_json(value: Optional[str], fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def get_knowledge_status() -> Dict[str, Any]:
    try:
        # sqlite3.Connection 的上下文管理器只负责提交/回滚，不会自动 close。
        # 用 closing 包住连接，避免知识库查询在进程退出时积累 ResourceWarning。
        with closing(_connect()) as connection:
            metadata = dict(connection.execute("SELECT key, value FROM metadata"))
            counts = {
                "documents": connection.execute("SELECT COUNT(1) FROM documents").fetchone()[0],
                "chunks": connection.execute("SELECT COUNT(1) FROM chunks").fetchone()[0],
                "claims": connection.execute("SELECT COUNT(1) FROM claims").fetchone()[0],
                "decisions": connection.execute(
                    "SELECT COUNT(1) FROM claims WHERE decision_enabled = 1"
                ).fetchone()[0],
            }
            course_rows = connection.execute(
                """
                SELECT course_id, MIN(course_name) AS course_name, COUNT(1) AS document_count
                FROM documents GROUP BY course_id ORDER BY course_id
                """
            ).fetchall()
            topic_counter: Counter[str] = Counter()
            for row in connection.execute("SELECT topics_json FROM documents"):
                topic_counter.update(_parse_json(row["topics_json"], []))
        return {
            "available": True,
            "schema_version": metadata.get("bundle_schema"),
            "knowledge_version": metadata.get("schema_version"),
            "built_at": metadata.get("bundle_built_at"),
            "counts": counts,
            "courses": [dict(row) for row in course_rows],
            "topics": [name for name, _ in topic_counter.most_common()],
            "decision_message": NO_VERIFIED_KNOWLEDGE if counts["decisions"] == 0 else None,
        }
    except Exception as exc:
        return {
            "available": False,
            "error": str(exc),
            "counts": {"documents": 0, "chunks": 0, "claims": 0, "decisions": 0},
            "courses": [],
            "topics": [],
            "decision_message": NO_VERIFIED_KNOWLEDGE,
        }


def _query_terms(query: str) -> List[str]:
    compact = re.sub(r"\s+", "", query.casefold())
    terms: List[str] = []
    for token in re.findall(r"[a-z0-9_.%-]+|[\u3400-\u9fff]+", compact):
        if len(token) >= 3:
            terms.append(token[:12])
        if re.fullmatch(r"[\u3400-\u9fff]+", token):
            terms.extend(token[index : index + 3] for index in range(max(0, len(token) - 2)))
    unique: List[str] = []
    for term in terms:
        if term and term not in unique:
            unique.append(term)
    return unique[:24]


def _fts_query(query: str) -> Optional[str]:
    terms = _query_terms(query)
    if not terms:
        return None
    return " OR ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)


def _excerpt(text: str, query: str, length: int = 360) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if len(cleaned) <= length:
        return cleaned
    terms = _query_terms(query)
    positions = [cleaned.casefold().find(term) for term in terms]
    position = min((value for value in positions if value >= 0), default=0)
    start = max(0, position - 80)
    return ("..." if start else "") + cleaned[start : start + length] + "..."


def _filters(course_id: Optional[str], topic: Optional[str], table_alias: str) -> tuple[str, List[Any]]:
    clauses: List[str] = []
    params: List[Any] = []
    if course_id:
        clauses.append(f"{table_alias}.course_id = ?")
        params.append(course_id.upper())
    if topic:
        topic_column = "topics_json" if table_alias == "c" else "topic"
        clauses.append(f"COALESCE({table_alias}.{topic_column}, '') LIKE ?")
        params.append(f"%{topic}%")
    return (" AND " + " AND ".join(clauses)) if clauses else "", params


def _search_chunks(
    connection: sqlite3.Connection,
    query: str,
    course_id: Optional[str],
    topic: Optional[str],
    limit: int,
) -> List[Dict[str, Any]]:
    filters, filter_params = _filters(course_id, topic, "c")
    fts = _fts_query(query)
    if fts:
        rows = connection.execute(
            f"""
            SELECT c.*, bm25(chunk_fts) AS rank
            FROM chunk_fts JOIN chunks c ON c.chunk_id = chunk_fts.chunk_id
            WHERE chunk_fts MATCH ? {filters}
            ORDER BY rank LIMIT ?
            """,
            [fts, *filter_params, limit],
        ).fetchall()
    else:
        pattern = f"%{query}%"
        rows = connection.execute(
            f"""
            SELECT c.*, -0.1 AS rank FROM chunks c
            WHERE (c.title LIKE ? OR c.section LIKE ? OR c.text LIKE ?) {filters}
            LIMIT ?
            """,
            [pattern, pattern, pattern, *filter_params, limit],
        ).fetchall()
    return [
        {
            "result_type": "document_chunk",
            "id": row["chunk_id"],
            "course_id": row["course_id"],
            "title": row["title"],
            "section": row["section"],
            "source_path": row["source_path"],
            "excerpt": _excerpt(row["text"], query),
            "topics": _parse_json(row["topics_json"], []),
            "risk_tags": _parse_json(row["risk_tags_json"], []),
            "source_status": "参考资料",
            "decision_enabled": row["decision_enabled"] == 1,
            "score": round(1 / (1 + abs(float(row["rank"] or 0))), 5),
        }
        for row in rows
    ]


def _search_claims(
    connection: sqlite3.Connection,
    query: str,
    course_id: Optional[str],
    topic: Optional[str],
    decision_only: bool,
    limit: int,
) -> List[Dict[str, Any]]:
    filters, filter_params = _filters(course_id, topic, "c")
    if decision_only:
        filters += " AND c.decision_enabled = 1"
    fts = _fts_query(query)
    if fts:
        rows = connection.execute(
            f"""
            SELECT c.*, bm25(claim_fts) AS rank
            FROM claim_fts JOIN claims c ON c.knowledge_id = claim_fts.knowledge_id
            WHERE claim_fts MATCH ? {filters}
            ORDER BY rank LIMIT ?
            """,
            [fts, *filter_params, limit],
        ).fetchall()
    else:
        pattern = f"%{query}%"
        rows = connection.execute(
            f"""
            SELECT c.*, -0.1 AS rank FROM claims c
            WHERE (c.title LIKE ? OR c.topic LIKE ? OR c.claim_text LIKE ? OR c.screen_fact LIKE ?) {filters}
            LIMIT ?
            """,
            [pattern, pattern, pattern, pattern, *filter_params, limit],
        ).fetchall()
    return [
        {
            "result_type": "structured_claim",
            "id": row["knowledge_id"],
            "course_id": row["course_id"],
            "title": row["title"] or row["topic"] or row["knowledge_id"],
            "section": " / ".join(value for value in (row["topic"], row["subtopic"]) if value),
            "source_path": row["source_path"],
            "excerpt": _excerpt("\n".join(value for value in (row["claim_text"], row["screen_fact"]) if value), query),
            "topics": [value for value in (row["topic"], row["subtopic"]) if value],
            "risk_tags": [row["risk_type"]] if row["risk_type"] else [],
            "source_status": row["source_status"] or "参考资料",
            "decision_enabled": row["decision_enabled"] == 1,
            "applicable_conditions": row["applicable_conditions"],
            "excluded_conditions": row["excluded_conditions"],
            "unproven_content": row["unproven_content"],
            "timeliness_risk": row["timeliness_risk"],
            "decision_reason": row["decision_reason"],
            "score": round(1 / (1 + abs(float(row["rank"] or 0))) + 0.02, 5),
        }
        for row in rows
    ]


def search_knowledge(
    query: str,
    course_id: Optional[str] = None,
    topic: Optional[str] = None,
    decision_only: bool = False,
    limit: int = 8,
) -> Dict[str, Any]:
    normalized = query.strip()
    if not normalized:
        raise ValueError("检索问题不能为空")
    limit = max(1, min(limit, 20))
    with closing(_connect()) as connection:
        if decision_only:
            results = _search_claims(connection, normalized, course_id, topic, True, limit)
        else:
            results = _search_claims(connection, normalized, course_id, topic, False, limit)
            results.extend(_search_chunks(connection, normalized, course_id, topic, limit))
            results.sort(key=lambda item: (-item["score"], item["source_path"] or ""))
            results = results[:limit]
    return {
        "query": normalized,
        "decision_only": decision_only,
        "count": len(results),
        "decision_count": sum(1 for result in results if result["decision_enabled"]),
        "message": NO_VERIFIED_KNOWLEDGE if decision_only and not results else None,
        "results": results,
    }


def _fallback_answer(query: str, results: List[Dict[str, Any]], business_context: Optional[Dict[str, Any]]) -> str:
    if not results:
        return NO_VERIFIED_KNOWLEDGE
    verified = [result for result in results if result["decision_enabled"]]
    lines = [f"围绕“{query}”找到 {len(results)} 条相关证据。"]
    if verified:
        lines.append(f"其中 {len(verified)} 条已通过决策闸门。")
    else:
        lines.append("当前命中内容均为参考资料或待复核观点，不能直接当作确定操作指令。")
    if business_context:
        lines.append("已附带当前店铺数据上下文，建议先核对净交易、退款、结算和成本口径。")
    lines.append("优先核对来源：")
    for result in results[:3]:
        lines.append(f"- {result['title']}（{result['course_id']}，{result['source_status']}）")
    lines.append("下一步应在当前商家后台确认相关入口、字段和系统提示，再设计单变量、可回滚的小范围测试。")
    return "\n".join(lines)


def _assistant_prompt(query: str, results: List[Dict[str, Any]], business_context: Optional[Dict[str, Any]]) -> str:
    evidence = []
    for index, result in enumerate(results[:8], start=1):
        evidence.append(
            {
                "index": index,
                "course_id": result["course_id"],
                "title": result["title"],
                "source_path": result["source_path"],
                "source_status": result["source_status"],
                "decision_enabled": result["decision_enabled"],
                "excerpt": result["excerpt"],
                "applicable_conditions": result.get("applicable_conditions"),
                "unproven_content": result.get("unproven_content"),
                "risk_tags": result.get("risk_tags"),
            }
        )
    return f"""用户问题：{query}

当前店铺数据上下文：
{json.dumps(business_context or {}, ensure_ascii=False, indent=2)[:6000]}

知识库证据：
{json.dumps(evidence, ensure_ascii=False, indent=2)[:14000]}

请按以下结构用中文回答：
### 结论
### 数据证据
### 知识证据
### 建议的小范围测试
### 观察窗口与停止条件
### 仍需核验

要求：
1. 严格区分当前数据事实、课程讲师观点和你的推断。
2. decision_enabled=false 的内容只能作为待验证假设，不能写成确定指令。
3. 不得建议补单、刷单、虚假成交、风控绕过或未授权搬图。
4. 不得自动要求改价、建券、调预算或批量建链接；只能给人工审核的测试草案。
5. 引用证据时写明课程编号和来源标题。
6. 没有数据时明确说明，不编造阈值、利润或平台机制。
"""


def _requires_temperature_one(exc: Exception) -> bool:
    message = str(exc).casefold()
    return "invalid temperature" in message and (
        "only 1 is allowed" in message or "only 1.0 is allowed" in message
    )


def answer_with_knowledge(
    query: str,
    course_id: Optional[str] = None,
    topic: Optional[str] = None,
    limit: int = 8,
    use_ai: bool = True,
    business_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    search = search_knowledge(query, course_id=course_id, topic=topic, limit=limit)
    results = search["results"]
    fallback = _fallback_answer(query, results, business_context)
    if not use_ai or not results:
        return {**search, "answer": fallback, "answer_source": "retrieval", "ai_error": None}

    config = get_config_defaults()
    api_key = str(config.get("api_key") or "").strip()
    if not api_key:
        return {**search, "answer": fallback, "answer_source": "retrieval", "ai_error": None}
    prompt = _assistant_prompt(query, results, business_context)
    llm_options: Dict[str, Any] = {
        "api_key": api_key,
        "base_url": config.get("base_url", "https://api.kimi.com/coding/v1"),
        "model": config.get("model", "kimi-coding"),
        "temperature": float(config.get("temperature", 1.0)),
        "reasoning_effort": config.get("reasoning_effort", "low"),
        "system_prompt": (
            "你是只读的拼多多运营决策助理。你的建议必须可审计、引用来源、标明不确定性，"
            "并以真实结算利润和当前平台状态为准。"
        ),
        "timeout": max(int(config.get("timeout", 60)), ASSISTANT_MIN_TIMEOUT_SECONDS),
        "max_completion_tokens": min(int(config.get("max_completion_tokens", 16384)), 8192),
    }
    try:
        try:
            answer = call_llm(prompt, **llm_options)
        except RuntimeError as exc:
            if llm_options["temperature"] == 1.0 or not _requires_temperature_one(exc):
                raise
            llm_options["temperature"] = 1.0
            answer = call_llm(prompt, **llm_options)
        return {**search, "answer": answer, "answer_source": "llm", "ai_error": None}
    except Exception as exc:
        return {
            **search,
            "answer": fallback,
            "answer_source": "retrieval_fallback",
            "ai_error": str(exc),
        }
