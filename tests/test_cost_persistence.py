import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import backup
import cost_manager


class CostPersistenceTests(unittest.TestCase):
    def test_save_cost_config_replaces_file_atomically(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            costs_file = data_dir / "costs.json"
            with patch.object(cost_manager, "DATA_DIR", data_dir), patch.object(cost_manager, "COSTS_FILE", costs_file):
                cost_manager.save_cost_config({"global_merchant_costs": {"A": {"product_cost": 12}}})
                self.assertEqual(cost_manager.load_cost_config()["global_merchant_costs"]["A"]["product_cost"], 12)
                self.assertFalse(costs_file.with_name(".costs.json.tmp").exists())

    def test_corrupt_cost_config_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            costs_file = data_dir / "costs.json"
            data_dir.mkdir()
            costs_file.write_text("{", encoding="utf-8")
            with patch.object(cost_manager, "DATA_DIR", data_dir), patch.object(cost_manager, "COSTS_FILE", costs_file):
                with self.assertRaises(RuntimeError):
                    cost_manager.load_cost_config()

    def test_backup_failure_does_not_leave_zero_byte_archive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            backup_dir = data_dir / "backups"
            data_dir.mkdir()
            (data_dir / "costs.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
            with patch.object(backup, "DATA_DIR", data_dir), patch.object(backup, "BACKUP_DIR", backup_dir):
                backup_path = Path(backup.create_backup())
                self.assertTrue(backup_path.exists())
                self.assertGreater(backup_path.stat().st_size, 0)
                self.assertFalse(list(backup_dir.glob(".*.tmp")))


if __name__ == "__main__":
    unittest.main()
