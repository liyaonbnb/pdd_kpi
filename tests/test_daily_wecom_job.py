import datetime
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import patch

import daily_wecom_job


class DailyWeComJobTests(unittest.TestCase):
    def _paths(self, temp_dir: str):
        data_dir = Path(temp_dir)
        return patch.multiple(
            daily_wecom_job,
            STATE_FILE=data_dir / "state.json",
            LOCK_FILE=data_dir / "job.lock",
        )

    def test_dry_run_generates_report_without_sending(self):
        with tempfile.TemporaryDirectory() as temp_dir, self._paths(temp_dir), patch.object(
            daily_wecom_job, "get_config_defaults", return_value={"api_key": ""}
        ), patch.object(
            daily_wecom_job, "build_daily_report", return_value="日报内容"
        ) as build_report, patch.object(
            daily_wecom_job, "send_wecom_report_service"
        ) as send:
            result = daily_wecom_job.run_daily_wecom_job(
                datetime.date(2026, 8, 11),
                dry_run=True,
            )

        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["data_date"], "2026-08-10")
        self.assertEqual(result["content_length"], 4)
        build_report.assert_called_once_with(
            datetime.date(2026, 8, 11),
            ai_config={"api_key": ""},
        )
        send.assert_not_called()

    def test_successful_send_is_persisted_and_not_repeated(self):
        draft = {"draft_id": "draft-1", "content": "日报内容"}
        config = {"bot_id": "bot", "secret": "secret", "chat_id": "wr_group"}
        with tempfile.TemporaryDirectory() as temp_dir, self._paths(temp_dir), patch.object(
            daily_wecom_job, "load_wecom_config", return_value=config
        ), patch.object(
            daily_wecom_job, "preview_wecom_report_service", return_value=draft
        ) as preview, patch.object(
            daily_wecom_job,
            "send_wecom_report_service",
            return_value={"errcode": 0},
        ) as send:
            first = daily_wecom_job.run_daily_wecom_job(datetime.date(2026, 8, 11))
            second = daily_wecom_job.run_daily_wecom_job(datetime.date(2026, 8, 11))

        self.assertEqual(first["status"], "sent")
        self.assertEqual(second["status"], "skipped")
        preview.assert_called_once_with(datetime.date(2026, 8, 11))
        send.assert_called_once_with(datetime.date(2026, 8, 11), config, "draft-1")

    def test_failed_send_is_not_recorded_as_sent(self):
        config = {"bot_id": "bot", "secret": "secret", "chat_id": "wr_group"}
        with tempfile.TemporaryDirectory() as temp_dir, self._paths(temp_dir), patch.object(
            daily_wecom_job, "load_wecom_config", return_value=config
        ), patch.object(
            daily_wecom_job,
            "preview_wecom_report_service",
            return_value={"draft_id": "draft-1"},
        ), patch.object(
            daily_wecom_job,
            "send_wecom_report_service",
            side_effect=RuntimeError("send failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "send failed"):
                daily_wecom_job.run_daily_wecom_job(datetime.date(2026, 8, 11))
            state = json.loads(daily_wecom_job.STATE_FILE.read_text(encoding="utf-8"))
            self.assertEqual(state["last_status"], "failed")
            self.assertEqual(state["last_error"], "send failed")
            self.assertNotIn("2026-08-11", state.get("sent_report_dates", []))

    def test_schedule_status_falls_back_to_cron_log(self):
        with tempfile.TemporaryDirectory() as temp_dir, self._paths(temp_dir), patch.object(
            daily_wecom_job, "LOG_FILE", Path(temp_dir) / "cron.log"
        ), patch.object(daily_wecom_job, "_cron_is_enabled", return_value=True):
            daily_wecom_job.LOG_FILE.write_text(
                '{"status":"failed","error":"missing metric"}\n',
                encoding="utf-8",
            )

            status = daily_wecom_job.get_daily_wecom_schedule_status()

        self.assertTrue(status["enabled"])
        self.assertEqual(status["schedule_time"], "10:30")
        self.assertEqual(status["timezone"], "Asia/Shanghai")
        self.assertEqual(status["last_status"], "failed")
        self.assertEqual(status["last_error"], "missing metric")

    def test_corrupt_state_fails_closed_instead_of_resending(self):
        with tempfile.TemporaryDirectory() as temp_dir, self._paths(temp_dir), patch.object(
            daily_wecom_job, "send_wecom_report_service"
        ) as send:
            daily_wecom_job.STATE_FILE.write_text("not-json", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "状态文件损坏"):
                daily_wecom_job.run_daily_wecom_job(datetime.date(2026, 8, 11))

        send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
