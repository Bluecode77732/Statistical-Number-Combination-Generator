import os
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

    # 목적: 백업을 만들기만 하고, 정리는 prune_backups를 부를 때 최근 BACKUP_KEEP개로 줄이는지 확인한다.
    # 이유: 정리를 저장 성공 뒤로 옮겼다(감사 A-11). 백업 자체가 오래된 복원 지점을 지우면 안 된다.
    # 방법: 한도보다 3개 많이 백업한 뒤 개수를 보고, 정리 후 남은 것이 가장 최근 것들인지 본다.
    def test_backup_created_and_pruned_to_limit(self):
        excel_store.write_store(self.path, make_draws(5), [])
        base = datetime(2026, 1, 1, 0, 0, 0)
        for i in range(excel_store.BACKUP_KEEP + 3):
            excel_store.backup_store(self.path, base + timedelta(seconds=i))
        self.assertEqual(len(list((self.dir / "backup").iterdir())), excel_store.BACKUP_KEEP + 3)
        excel_store.prune_backups(self.path)
        backups = sorted((self.dir / "backup").iterdir())
        self.assertEqual(len(backups), excel_store.BACKUP_KEEP)
        self.assertTrue(backups[-1].name.endswith("_000012.xlsx"))  # 가장 최근 것이 남음
        self.assertTrue(backups[0].name.endswith("_000003.xlsx"))

    # 목적: 원본과 같은 백업만 거두고, 원본과 다른 백업은 남기는지 확인한다.
    # 이유: 저장 실패 뒤 거두는 백업이 실제 복원 지점이면 안 된다(규칙 4).
    # 방법: 백업 직후(같음)와 원본을 바꾼 뒤(다름) 각각 discard_backup_if_unchanged를 부른다.
    def test_discard_backup_only_when_identical(self):
        excel_store.write_store(self.path, make_draws(5), [])
        same = excel_store.backup_store(self.path, datetime(2026, 1, 1, 0, 0, 0))
        self.assertTrue(excel_store.discard_backup_if_unchanged(self.path, same))
        self.assertFalse(same.exists())
        kept = excel_store.backup_store(self.path, datetime(2026, 1, 1, 0, 0, 1))
        excel_store.write_store(self.path, make_draws(6), [])
        self.assertFalse(excel_store.discard_backup_if_unchanged(self.path, kept))
        self.assertTrue(kept.exists())

    def test_corrupt_file_raises_store_error(self):
        self.path.write_bytes(b"not an excel file")
        with self.assertRaises(excel_store.StoreError):
            excel_store.read_store(self.path)

    def blocked_folder(self) -> Path:
        # 부모가 파일이면 폴더를 만들 수 없다. 권한 설정 없이 쓰기 불가 폴더를 흉내 낸다.
        blocker = self.dir / "blocker"
        blocker.write_bytes(b"x")
        return blocker / "data"

    def test_ensure_writable_dir_creates_folder_and_leaves_no_probe(self):
        folder = self.dir / "new" / "data"
        excel_store.ensure_writable_dir(folder)
        self.assertTrue(folder.is_dir())
        self.assertEqual(list(folder.iterdir()), [])

    def test_unwritable_folder_raises_store_error_with_guidance(self):
        with self.assertRaises(excel_store.StoreError) as ctx:
            excel_store.ensure_writable_dir(self.blocked_folder())
        self.assertIn("쓰기 권한", str(ctx.exception))

    def test_write_store_in_unwritable_folder_raises_store_error(self):
        with self.assertRaises(excel_store.StoreError):
            excel_store.write_store(self.blocked_folder() / "lotto.xlsx", make_draws(5), [])

    def make_temp(self, name: str, age_seconds: float) -> Path:
        p = self.dir / name
        p.write_bytes(b"x")
        old = p.stat().st_mtime - age_seconds
        os.utime(p, (old, old))
        return p

    def test_cleanup_removes_only_stale_app_temp_files(self):
        stale_store = self.make_temp(".lotto.tmp-111.xlsx", excel_store.STALE_TEMP_SECONDS + 60)
        stale_backtest = self.make_temp(".backtest.tmp-222.xlsx", excel_store.STALE_TEMP_SECONDS + 60)
        fresh = self.make_temp(".lotto.tmp-333.xlsx", 10)  # 다른 실행기가 저장 중일 수 있는 파일
        other = self.make_temp(".other.tmp-444.xlsx", excel_store.STALE_TEMP_SECONDS + 60)
        excel_store.write_store(self.path, make_draws(5), [])
        (self.dir / "backup").mkdir()
        removed = excel_store.cleanup_stale_temp(self.dir)
        self.assertEqual(sorted(removed), sorted([stale_store.name, stale_backtest.name]))
        self.assertFalse(stale_store.exists() or stale_backtest.exists())
        self.assertTrue(fresh.exists() and other.exists())
        self.assertTrue(self.path.exists() and (self.dir / "backup").is_dir())  # 실제 데이터는 그대로

    def test_cleanup_ignores_missing_folder(self):
        self.assertEqual(excel_store.cleanup_stale_temp(self.dir / "nope"), [])

    def test_backup_in_unwritable_folder_raises_store_error(self):
        excel_store.write_store(self.path, make_draws(5), [])
        with mock.patch.object(Path, "mkdir", side_effect=FileExistsError("blocked")):
            with self.assertRaises(excel_store.StoreError):
                excel_store.backup_store(self.path)


if __name__ == "__main__":
    unittest.main()
