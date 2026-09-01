"""Export the legacy data/users.json into a V2 import payload.

The script never sends or prints passwords.  It preserves bcrypt hashes so the
V2 API can import accounts without requiring plaintext credentials.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_PAGES = [
    "overview", "stores", "import", "metrics", "orders", "costs",
    "douyin_overview", "douyin_import", "douyin_metrics", "douyin_orders", "douyin_costs",
    "tmall_overview", "tmall_import", "tmall_metrics", "tmall_orders", "tmall_costs",
    "wechat_overview", "wechat_import", "wechat_metrics", "wechat_orders", "wechat_costs",
    "ai_wecom", "knowledge_assistant",
]


def build_payload(source: Path) -> dict:
    raw = json.loads(source.read_text(encoding="utf-8"))
    users = raw.get("users", raw)
    result = []
    for username, user in users.items():
        role = user.get("role", "sub")
        result.append({
            "username": username,
            "password_hash": user.get("password_hash"),
            "role": role,
            "display_name": user.get("display_name") or username,
            "allowed_stores": list(user.get("allowed_stores") or []),
            "allowed_pages": list(user.get("allowed_pages") or ([] if role == "master" else DEFAULT_PAGES)),
            "legacy_username": username,
            "password_changed": bool(user.get("password_changed", True)),
        })
    return {"users": result}


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 V2 旧版账号迁移 payload")
    parser.add_argument("source", type=Path, nargs="?", default=Path("data/users.json"))
    parser.add_argument("output", type=Path, nargs="?", default=Path("v2/local_data/legacy_users_payload.json"))
    args = parser.parse_args()
    payload = build_payload(args.source)
    if any(not user.get("password_hash") for user in payload["users"]):
        raise SystemExit("存在缺少 password_hash 的账号，已停止生成")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已生成 {len(payload['users'])} 个账号的迁移文件：{args.output}")


if __name__ == "__main__":
    main()
