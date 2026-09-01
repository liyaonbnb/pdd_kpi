import json
import tempfile
import unittest
from pathlib import Path

from scripts.migrate_legacy_users import build_payload


class V2AuthMigrationTests(unittest.TestCase):
    def test_legacy_users_are_converted_without_plaintext_password(self):
        raw = {
            "users": {
                "admin": {"role": "master", "password_hash": "$2b$hash", "allowed_stores": []},
                "ops": {"role": "sub", "password_hash": "$2b$hash2", "allowed_stores": ["店A"]},
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "users.json"
            source.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
            payload = build_payload(source)
        self.assertEqual([u["username"] for u in payload["users"]], ["admin", "ops"])
        self.assertEqual(payload["users"][1]["allowed_stores"], ["店A"])
        self.assertNotIn("password", payload["users"][0])
        self.assertEqual(payload["users"][0]["password_hash"], "$2b$hash")
        self.assertTrue(payload["users"][1]["allowed_pages"])


if __name__ == "__main__":
    unittest.main()
