import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

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

    def test_sync_cleans_stale_temp_left_by_killed_save(self):
        leftover = self.path.parent / ".lotto.tmp-999.xlsx"
        leftover.write_bytes(b"half written")
        old = leftover.stat().st_mtime - excel_store.STALE_TEMP_SECONDS - 60
        os.utime(leftover, (old, old))
        report = self.sync()
        self.assertEqual(report.status, "created")
        self.assertFalse(leftover.exists())

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

    # 목적: 저장이 계속 실패해도 이전 복원 지점이 지워지지 않는지 재현한다(감사 E8, A-11).
    # 이유: 예전에는 실패한 실행마다 원본과 같은 백업이 생기고 오래된 백업이 정리되어, 12번 실패하면 서로 다른
    #       복원 지점이 1개만 남았다.
    # 방법: 내용이 서로 다른 오래된 백업 10개를 둔 채 교체 단계를 12번 실패시키고, 백업 목록과 원본이 그대로인지 본다.
    #       이어서 저장에 성공하면 새 백업이 생기고 가장 오래된 것 하나만 정리되는지 본다.
    def test_repeated_save_failure_keeps_old_restore_points(self):
        data_sync.sync(self.path, http_get=FakeServer(self.draws[:30]), now=self.clock, sleep=no_sleep)
        backup_dir = self.path.parent / "backup"
        backup_dir.mkdir()
        for i in range(excel_store.BACKUP_KEEP):
            excel_store.write_store(backup_dir / f"lotto_20260901_0000{i:02d}.xlsx", make_draws(20 + i), [])
        old_backups = self.backups()
        original = self.path.read_bytes()
        with mock.patch("excel_store.os.replace", side_effect=OSError("disk full")):
            for _ in range(12):
                report = self.sync()
                self.assertFalse(report.saved)
                self.assertIsNone(report.backup_path)
        self.assertEqual(self.backups(), old_backups)
        self.assertEqual(self.path.read_bytes(), original)

        report = self.sync()
        self.assertTrue(report.saved)
        after = self.backups()
        self.assertEqual(len(after), excel_store.BACKUP_KEEP)
        self.assertEqual(after[:-1], old_backups[1:])
        self.assertEqual(str(after[-1]), report.backup_path)

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

    # 목적: 기존 엑셀이 있는데 공식 사이트가 빈 목록을 주면 "이미 최신"이 아니라 업데이트 실패로 보는지 확인한다.
    # 이유: 확인한 것이 없는데 "이미 최신"으로 보여 사이트 변경을 놓칠 수 있었다(감사 A-04, 재현 E1).
    # 방법: 한 번 만들고, 모든 회차를 지운 가짜 서버로 다시 돌린다. 상태, 안내, 파일·백업이 그대로인지 본다.
    def test_empty_official_response_is_a_failure(self):
        self.sync()
        before = self.path.read_bytes()
        self.server.draws = {}
        report = self.sync()
        self.assertEqual(report.status, "offline")
        self.assertIn("빈 응답", report.messages[-1])
        self.assertEqual(report.latest_round, 40)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.backups(), [])

    # 목적: 한 쪽(10회차)이 전부 불량이어도 그 뒤 회차를 계속 받는지 확인한다.
    # 이유: 불량 쪽에서 수집이 멈춰 뒤 회차를 받지 못하고 최신 회차가 낮게 보였다(감사 A-06, 재현 E9).
    # 방법: 11~20회 응답을 모두 망가뜨린 서버로 처음 만든다. 21~40회가 들어오고 11~20회는 거부·빠짐으로 남는지 본다.
    def test_bad_page_does_not_stop_collection(self):
        for r in range(11, 21):
            self.server.bad_rounds[r] = {"tm1WnNo": 99}
        report = self.sync()
        self.assertEqual(report.latest_round, 40)
        self.assertEqual(sorted(r["round"] for r in report.rejected), list(range(11, 21)))
        self.assertEqual(report.issues["missing"], list(range(11, 21)))

    # 목적: 공식에 없는 회차가 엑셀에 있으면 분석에서 빼고, 백업한 뒤 엑셀에서도 지우고 기록하는지 확인한다.
    # 이유: 손으로 넣은 9999회가 남아 분석에 쓰이고 다음 후보 대상이 10000회가 되었다(감사 A-07, 재현 E10).
    #       사용자 결정(2026-11-10): 분석에서 빼고 엑셀에서도 제거.
    # 방법: 만든 엑셀에 9999회를 넣어 저장한 뒤 다시 돌리고, 결과·파일·변경기록·백업을 본다.
    def test_round_missing_from_official_source_is_removed(self):
        self.sync()
        stored = excel_store.read_store(self.path)
        fake = LottoDraw(9999, [1, 2, 3, 4, 5, 6], 7, "2099-01-01")
        excel_store.write_store(self.path, stored.draws + [fake], stored.log_rows)
        report = self.sync()
        self.assertEqual(report.status, "updated")
        self.assertEqual([r["round"] for r in report.removed], [9999])
        self.assertEqual(report.latest_round, 40)
        self.assertEqual(report.issues["missing"], [])
        again = excel_store.read_store(self.path)
        self.assertNotIn(9999, [d.round_no for d in again.draws])
        self.assertTrue(any(row[2] == "공식에 없는 회차 삭제" for row in again.log_rows))
        self.assertEqual(len(self.backups()), 1)
        self.assertEqual(self.sync().status, "up_to_date")

    def test_unconfirmed_rounds_are_never_written(self):
        report = self.sync()
        self.assertEqual(report.latest_round, max(d.round_no for d in self.draws))


if __name__ == "__main__":
    unittest.main()
