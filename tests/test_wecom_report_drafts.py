import datetime
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import services
import wecom_report_drafts


class WeComReportDraftTests(unittest.TestCase):
    def test_draft_persists_and_cannot_be_sent_twice(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            drafts_file = data_dir / "wecom_report_drafts.json"
            with patch.object(wecom_report_drafts, "DATA_DIR", data_dir), patch.object(
                wecom_report_drafts, "DRAFTS_FILE", drafts_file
            ):
                draft = wecom_report_drafts.create_report_draft(
                    "完整日报内容",
                    "2026-08-11",
                    platform="pdd",
                )
                loaded = wecom_report_drafts.get_report_draft(
                    draft["draft_id"],
                    report_date="2026-08-11",
                    platform="pdd",
                )
                self.assertEqual(loaded["content"], "完整日报内容")

                wecom_report_drafts.mark_report_draft_sent(draft["draft_id"])
                with self.assertRaisesRegex(ValueError, "已经发送过"):
                    wecom_report_drafts.get_report_draft(
                        draft["draft_id"],
                        report_date="2026-08-11",
                        platform="pdd",
                    )

    def test_send_uses_existing_draft_without_regenerating_report(self):
        draft = {"draft_id": "draft-1", "content": "已经确认的日报"}
        with patch.object(services, "get_report_draft", return_value=draft), patch.object(
            services, "send_wecom_report", return_value={"errcode": 0}
        ) as send, patch.object(services, "mark_report_draft_sent") as mark_sent, patch.object(
            services, "build_daily_report"
        ) as build:
            result = services.send_wecom_report_service(
                datetime.date(2026, 8, 11),
                {"chat_id": "new-chat"},
                draft_id="draft-1",
            )

        self.assertEqual(result["errcode"], 0)
        build.assert_not_called()
        send.assert_called_once_with("已经确认的日报", {"chat_id": "new-chat"})
        mark_sent.assert_called_once_with("draft-1")


if __name__ == "__main__":
    unittest.main()
