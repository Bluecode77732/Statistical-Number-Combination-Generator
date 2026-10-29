import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import excel_store
from tests.helpers import make_draws


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.path = self.dir / "lotto.xlsx"

    def tearDown(self):
        self.tmp.cleanup()

    def test_roundtrip_keeps_values_dates_and_log(self):
        draws = make_draws(30)
        log = [["2026-01-01 00:00:00", 3, "추가", "x"]]
        excel_store.write_store(self.path, draws, log)
        stored = excel_store.read_store(self.path)
        self.assertEqual([(d.round_no, d.numbers, d.bonus, d.draw_date) for d in stored.draws],
                         [(d.round_no, d.numbers, d.bonus, d.draw_date) for d in draws])
        self.assertEqual(stored.log_rows, log)

    def test_failed_save_leaves_original_untouched(self):
        excel_store.write_store(self.path, make_draws(10), [])
        before = self.path.read_bytes()
        with mock.patch("excel_store.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(excel_store.StoreError):
                excel_store.write_store(self.path, make_draws(20), [])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual([p.name for p in self.dir.iterdir()], ["lotto.xlsx"])  # 임시 파일이 남지 않음

    def test_locked_file_gives_close_excel_message(self):
        excel_store.write_store(self.path, make_draws(5), [])
        with mock.patch("excel_store.os.replace", side_effect=PermissionError("locked")):
            with self.assertRaises(excel_store.StoreError) as ctx:
                excel_store.write_store(self.path, make_draws(6), [])
        self.assertIn("열려 있어", str(ctx.exception))

    def test_backup_created_and_pruned_to_limit(self):
        excel_store.write_store(self.path, make_draws(5), [])
        base = datetime(2026, 1, 1, 0, 0, 0)
        for i in range(excel_store.BACKUP_KEEP + 3):
            excel_store.backup_store(self.path, base + timedelta(seconds=i))
        backups = sorted((self.dir / "backup").iterdir())
        self.assertEqual(len(backups), excel_store.BACKUP_KEEP)
        self.assertTrue(backups[-1].name.endswith("_000012.xlsx"))  # 가장 최근 것이 남음

    def test_corrupt_file_raises_store_error(self):
        self.path.write_bytes(b"not an excel file")
        with self.assertRaises(excel_store.StoreError):
            excel_store.read_store(self.path)


if __name__ == "__main__":
    unittest.main()
