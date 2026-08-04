import datetime
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import import_batches
import services
import storage


def _order_csv(rows):
    return pd.DataFrame(rows).to_csv(index=False).encode("utf-8-sig")


class ImportBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        data_dir = Path(self.temp_dir.name) / "data"
        processed_dir = data_dir / "processed"
        meta_file = data_dir / "meta.json"
        batch_dir = data_dir / "import_batches"
        replacements = [
            patch.object(storage, "DATA_DIR", data_dir),
            patch.object(storage, "PROCESSED_DIR", processed_dir),
            patch.object(storage, "META_FILE", meta_file),
            patch.object(import_batches, "BATCH_DIR", batch_dir),
            patch.object(import_batches, "BATCH_INDEX", batch_dir / "batches.json"),
            patch.object(import_batches, "DATA_DIR", data_dir),
            patch.object(import_batches, "PROCESSED_DIR", processed_dir),
            patch.object(import_batches, "META_FILE", meta_file),
            patch.object(services, "refresh_global_cost_codes_service", return_value={"added": 0}),
        ]
        self.patchers = replacements
        for patcher in self.patchers:
            patcher.start()
        storage.init_storage()

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp_dir.cleanup()

    def test_import_preview_and_rollback_restore_previous_orders(self):
        store = "测试店铺"
        old_orders = pd.DataFrame(
            [
                {
                    "order_id": "2608010001",
                    "order_time": "2026-08-01 10:00:00",
                    "order_status": "已付款",
                    "quantity": 1,
                    "user_paid": 10,
                }
            ]
        )
        storage.save_daily_data(
            pd.DataFrame(), pd.DataFrame(), old_orders,
            date="2026-08-01", store_name=store, meta={"order_file": "old.csv"},
        )
        content = _order_csv(
            [
                {
                    "order_id": "2608010001",
                    "order_time": "2026-08-01 10:00:00",
                    "order_status": "已发货",
                    "quantity": 1,
                    "user_paid": 12,
                },
                {
                    "order_id": "2608010002",
                    "order_time": "2026-08-01 11:00:00",
                    "order_status": "已付款",
                    "quantity": 2,
                    "user_paid": 20,
                },
            ]
        )

        preview = services.preview_daily_import(
            store, datetime.date(2026, 8, 1), order_bytes=content, order_filename="new.csv"
        )
        self.assertTrue(preview["can_import"], preview)
        self.assertEqual(preview["orders"]["new_orders"], 1)
        self.assertEqual(preview["orders"]["existing_orders"], 1)

        result = services.import_daily_data(
            store, datetime.date(2026, 8, 1), order_bytes=content,
            order_filename="new.csv", imported_by="tester",
        )
        self.assertEqual(len(storage.load_daily_orders("2026-08-01", store)), 2)
        self.assertEqual(import_batches.list_batches(store)[0]["status"], "imported")

        services.rollback_import_batch(result["batch_id"], "tester", False)
        restored = storage.load_daily_orders("2026-08-01", store)
        self.assertEqual(len(restored), 1)
        self.assertEqual(restored.iloc[0]["order_status"], "已付款")
        self.assertEqual(import_batches.list_batches(store)[0]["status"], "rolled_back")

    def test_preview_blocks_duplicate_file_and_invalid_rows(self):
        store = "测试店铺"
        content = _order_csv(
            [{"order_id": "2608010001", "order_time": "2026-08-01 10:00:00"}]
        )
        services.import_daily_data(
            store, datetime.date(2026, 8, 1), order_bytes=content,
            order_filename="orders.csv", imported_by="tester",
        )
        duplicate = services.preview_daily_import(
            store, datetime.date(2026, 8, 1), order_bytes=content, order_filename="orders.csv"
        )
        self.assertFalse(duplicate["can_import"])
        self.assertTrue(any("相同文件" in blocker for blocker in duplicate["blockers"]))

        invalid = _order_csv(
            [
                {"order_id": "abc", "order_time": "not-a-date"},
                {"order_id": "abc", "order_time": "not-a-date"},
            ]
        )
        preview = services.preview_daily_import(
            store, datetime.date(2026, 8, 1), order_bytes=invalid, order_filename="invalid.csv"
        )
        self.assertFalse(preview["can_import"])
        self.assertEqual(preview["orders"]["duplicate_order_ids"], 1)
        self.assertEqual(preview["orders"]["unresolved_dates"], 2)

    def test_only_latest_batch_can_be_rolled_back(self):
        store = "测试店铺"
        first = services.import_daily_data(
            store, datetime.date(2026, 8, 1),
            order_bytes=_order_csv([{"order_id": "2608010001", "order_time": "2026-08-01"}]),
            order_filename="first.csv", imported_by="tester",
        )
        services.import_daily_data(
            store, datetime.date(2026, 8, 2),
            order_bytes=_order_csv([{"order_id": "2608020001", "order_time": "2026-08-02"}]),
            order_filename="second.csv", imported_by="tester",
        )

        with self.assertRaisesRegex(ValueError, "最近一次"):
            services.rollback_import_batch(first["batch_id"], "tester", False)

    def test_cancelled_order_without_date_snapshots_its_previous_date(self):
        store = "测试店铺"
        old_orders = pd.DataFrame(
            [{"order_id": "legacy-id", "order_time": "2026-07-30", "order_status": "已付款"}]
        )
        storage.save_daily_data(
            pd.DataFrame(), pd.DataFrame(), old_orders, date="2026-07-30", store_name=store
        )
        cancelled = _order_csv(
            [{"order_id": "legacy-id", "order_time": "", "order_status": "交易关闭"}]
        )

        preview = services.preview_daily_import(
            store, datetime.date(2026, 8, 1), order_bytes=cancelled, order_filename="cancelled.csv"
        )
        self.assertIn("2026-07-30", preview["affected_dates"])

    def test_rollback_restores_order_moved_from_another_date(self):
        store = "测试店铺"
        old_orders = pd.DataFrame(
            [{"order_id": "2607300001", "order_time": "2026-07-30", "order_status": "已付款"}]
        )
        storage.save_daily_data(
            pd.DataFrame(), pd.DataFrame(), old_orders, date="2026-07-30", store_name=store
        )
        moved = _order_csv(
            [{"order_id": "2607300001", "order_time": "2026-08-01", "order_status": "已发货"}]
        )

        result = services.import_daily_data(
            store, datetime.date(2026, 8, 1), order_bytes=moved,
            order_filename="moved.csv", imported_by="tester",
        )
        self.assertEqual(len(storage.load_daily_orders("2026-07-30", store)), 0)
        self.assertEqual(len(storage.load_daily_orders("2026-08-01", store)), 1)

        services.rollback_import_batch(result["batch_id"], "tester", False)
        restored = storage.load_daily_orders("2026-07-30", store)
        self.assertEqual(len(restored), 1)
        self.assertEqual(restored.iloc[0]["order_status"], "已付款")
        with self.assertRaises(FileNotFoundError):
            storage.load_daily_orders("2026-08-01", store)

    def test_failed_import_automatically_restores_snapshot(self):
        store = "测试店铺"
        old_orders = pd.DataFrame(
            [{"order_id": "2608010001", "order_time": "2026-08-01", "order_status": "已付款"}]
        )
        storage.save_daily_data(
            pd.DataFrame(), pd.DataFrame(), old_orders, date="2026-08-01", store_name=store
        )
        content = _order_csv(
            [{"order_id": "2608010002", "order_time": "2026-08-01", "order_status": "已付款"}]
        )

        def break_after_write(*_args, **_kwargs):
            storage.save_daily_data(
                pd.DataFrame(), pd.DataFrame(), pd.DataFrame(),
                date="2026-08-01", store_name=store,
            )
            raise RuntimeError("simulated failure")

        with patch.object(services, "_apply_daily_import", side_effect=break_after_write):
            with self.assertRaisesRegex(RuntimeError, "simulated failure"):
                services.import_daily_data(
                    store, datetime.date(2026, 8, 1), order_bytes=content,
                    order_filename="broken.csv", imported_by="tester",
                )

        restored = storage.load_daily_orders("2026-08-01", store)
        self.assertEqual(len(restored), 1)
        self.assertEqual(restored.iloc[0]["order_id"], "2608010001")
        self.assertEqual(import_batches.list_batches(store)[0]["status"], "failed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
