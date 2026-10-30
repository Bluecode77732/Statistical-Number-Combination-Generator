import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import data_sync
import excel_store
from excel_loader import LottoDraw
from tests.helpers import FakeServer, make_draws, no_sleep


class Clock:
    def __init__(self):
        self.t = datetime(2026, 10, 1, 12, 0, 0)

    def __call__(self):
        self.t += timedelta(seconds=1)
        return self.t


class SyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "lotto.xlsx"
        self.draws = make_draws(40)
        self.server = FakeServer(self.draws)
        self.clock = Clock()

    def tearDown(self):
        self.tmp.cleanup()

    def sync(self):
        return data_sync.sync(self.path, http_get=self.server, now=self.clock, sleep=no_sleep)

    def backups(self):
        d = self.path.parent / "backup"
        return sorted(d.iterdir()) if d.exists() else []

    def test_creates_file_when_missing_without_backup(self):
        report = self.sync()
        self.assertEqual(report.status, "created")
        self.assertTrue(self.path.exists())
        self.assertEqual(report.latest_round, 40)
        self.assertEqual(self.backups(), [])

    def test_first_run_in_unwritable_folder_stops_before_fetching(self):
        blocker = Path(self.tmp.name) / "blocker"
        blocker.write_bytes(b"x")
        self.path = blocker / "data" / "lotto.xlsx"
        report = self.sync()
        self.assertEqual(report.status, "failed")
        self.assertEqual(self.server.calls, [])  # 몇 분 걸리는 수집을 시작하지 않는다
        self.assertIn("쓰기 권한", report.messages[-1])

    def test_second_run_is_up_to_date_and_makes_no_backup(self):
        self.sync()
        before = self.path.read_bytes()
        report = self.sync()
        self.assertEqual(report.status, "up_to_date")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.backups(), [])

    def test_new_rounds_added_once_with_backup(self):
        server = FakeServer(self.draws[:35])
        data_sync.sync(self.path, http_get=server, now=self.clock, sleep=no_sleep)
        report = self.sync()  # 서버에 36~40회가 새로 생김
        self.assertEqual(report.status, "updated")
        self.assertEqual(report.added, [36, 37, 38, 39, 40])
        self.assertEqual(len(self.backups()), 1)
        rounds = [d.round_no for d in excel_store.read_store(self.path).draws]
        self.assertEqual(rounds, list(range(1, 41)))  # 중복 삽입 없음
        self.assertEqual(self.sync().status, "up_to_date")

    def test_wrong_existing_value_is_corrected_and_logged(self):
        wrong = list(self.draws)
        d = wrong[37]
        fixed_num = next(n for n in range(1, 46) if n not in d.numbers and n != d.bonus)
        wrong[37] = LottoDraw(d.round_no, sorted([fixed_num] + d.numbers[1:]), d.bonus, d.draw_date)
        excel_store.write_store(self.path, wrong, [])
        report = self.sync()
        self.assertEqual([c["round"] for c in report.corrected], [38])
        stored = excel_store.read_store(self.path)
        self.assertEqual(stored.draws[37].numbers, self.draws[37].numbers)
        self.assertTrue(any(row[2] == "공식 값으로 수정" and row[1] == 38 for row in stored.log_rows))
        self.assertEqual(len(self.backups()), 1)

    def test_missing_and_duplicate_rounds_are_repaired(self):
        broken = self.draws[:5] + self.draws[6:] + [self.draws[20]]  # 6회 누락, 21회 중복
        excel_store.write_store(self.path, broken, [])
        report = self.sync()
        self.assertIn(6, report.added)
        self.assertEqual([d.round_no for d in excel_store.read_store(self.path).draws], list(range(1, 41)))
        self.assertEqual(report.issues, {"duplicates": [], "missing": []})

    def test_network_failure_keeps_existing_file(self):
        self.sync()
        before = self.path.read_bytes()
        self.server.fail_times = 99
        report = self.sync()
        self.assertEqual(report.status, "offline")
        self.assertEqual(report.latest_round, 40)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertTrue(any("업데이트 실패" in m for m in report.messages))

    def test_format_change_keeps_existing_file(self):
        self.sync()
        before = self.path.read_bytes()
        self.server.body_override = b"<html>moved</html>"
        report = self.sync()
        self.assertEqual(report.status, "offline")
        self.assertEqual(self.path.read_bytes(), before)

    def test_network_failure_without_file_fails(self):
        self.server.fail_times = 99
        report = self.sync()
        self.assertEqual(report.status, "failed")
        self.assertFalse(self.path.exists())

    def test_unconfirmed_rounds_are_never_written(self):
        report = self.sync()
        self.assertEqual(report.latest_round, max(d.round_no for d in self.draws))


if __name__ == "__main__":
    unittest.main()
