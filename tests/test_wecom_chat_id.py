import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import wecom


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


if __name__ == "__main__":
    unittest.main()
