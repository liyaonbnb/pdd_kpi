import datetime
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

import wecom
from routers import wecom as wecom_router


class WeComChatIdTests(unittest.TestCase):
    def test_new_chat_id_takes_precedence_over_legacy_value(self):
        with patch.object(wecom, "send_aibot_markdown", return_value={"errcode": 0}) as send:
            result = wecom.send_wecom_report(
                "日报",
                {
                    "send_type": "aibot",
                    "bot_id": "bot",
                    "secret": "secret",
                    "chat_id": "new-chat",
                    "chatid": "old-chat",
                },
            )
        self.assertEqual(result["errcode"], 0)
        self.assertEqual(send.call_args.kwargs["chatid"], "new-chat")

    def test_legacy_chatid_remains_supported(self):
        with patch.object(wecom, "send_aibot_markdown", return_value={"errcode": 0}) as send:
            wecom.send_wecom_report(
                "日报",
                {"send_type": "aibot", "bot_id": "bot", "secret": "secret", "chatid": "old-chat"},
            )
        self.assertEqual(send.call_args.kwargs["chatid"], "old-chat")

    def test_save_and_load_sync_both_config_field_names(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "wecom_config.json"
            with patch.object(wecom, "DATA_DIR", Path(temp_dir)), patch.object(wecom, "WECOM_CONFIG_FILE", config_path):
                wecom.save_wecom_config({"chat_id": "new-chat", "chatid": "old-chat"})
                loaded = wecom.load_wecom_config()
        self.assertEqual(loaded["chat_id"], "new-chat")
        self.assertEqual(loaded["chatid"], "new-chat")

    def test_frequency_limit_is_returned_as_actionable_429(self):
        request = wecom_router.SendReportRequest(
            report_date=datetime.date(2026, 8, 11),
            config={},
        )
        error = RuntimeError("aibot send msg frequency limit exceeded (errcode=846607)")
        with patch.object(wecom_router.services, "send_wecom_report_service", side_effect=error):
            with self.assertRaises(HTTPException) as raised:
                wecom_router.send_report(request, _={})
        self.assertEqual(raised.exception.status_code, 429)
        self.assertIn("发送频率受限", raised.exception.detail)


if __name__ == "__main__":
    unittest.main()
