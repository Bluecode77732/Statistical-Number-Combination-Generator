import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openpyxl import load_workbook

import collector
import excel_store
import pipeline
from tests.helpers import FakeServer, make_draws, no_sleep


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"LOTTO_DATA_DIR": self.tmp.name})
        self.env.start()
        self.server = FakeServer(make_draws(130))
        self.patches = [
            mock.patch.object(collector, "default_http_get", self.server),
            mock.patch.object(collector.time, "sleep", no_sleep),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.env.stop()
        self.tmp.cleanup()

    def test_full_run_produces_every_section(self):
        p = pipeline.Pipeline()
        p.run()
        self.assertEqual(p.state, "done")
        r = p.result
        self.assertEqual(r["sync"]["status"], "created")
        self.assertEqual(len(r["analysis"]), 9)
        self.assertTrue(r["backtest"]["ran"])
        self.assertTrue(os.path.exists(r["backtest"]["saved_path"]))
        self.assertEqual(len(r["candidates"]["numbers"]), 10)
        self.assertTrue(all(s["state"] == "done" for s in p.status()["steps"]))

    # 목적: 엑셀에 잘못된 행이 있으면 그 행을 건너뛰고 공식 값으로 다시 채우며, 검증 단계 문구에 밝히는지 확인한다.
    # 이유: 건너뛴 행이 있어도 검증 단계가 "이상 없음"으로 보였다(감사 A-14). 잘못된 행이 스스로 고쳐지는지도 함께 본다.
    # 방법: 한 번 돌려 엑셀을 만들고, 5회차의 보너스를 범위 밖 값으로 바꿔 저장한 뒤 다시 돌린다.
    def test_bad_excel_row_is_reported_and_repaired(self):
        pipeline.Pipeline().run()
        path = os.path.join(self.tmp.name, "lotto.xlsx")
        wb = load_workbook(path)
        ws = wb["당첨번호"]
        row = next(r for r in range(2, ws.max_row + 1) if ws.cell(r, 1).value == 5)
        ws.cell(row, 9).value = 99
        wb.save(path)
        wb.close()

        p = pipeline.Pipeline()
        p.run()
        self.assertEqual(p.state, "done")
        self.assertEqual(p.steps["validate"]["state"], "warning")
        self.assertIn("건너뛴 엑셀 행 1개", p.steps["validate"]["message"])
        self.assertEqual(len(p.result["validation"]["skipped_rows"]), 1)
        fixed = excel_store.read_store(Path(path))
        self.assertEqual(fixed.skipped_rows, [])
        self.assertEqual(next(d for d in fixed.draws if d.round_no == 5).bonus, self.server.draws[5].bonus)

    # 목적: 엑셀 저장에 실패하면 업데이트 단계 문구에 "반영하지 못함"이 드러나는지 확인한다.
    # 이유: 저장하지 못했는데도 "새로 만듦"으로만 보여 파일이 생긴 줄 알 수 있었다(감사 A-14).
    # 방법: write_store가 StoreError를 내도록 바꿔 첫 실행을 돌리고 sync 단계의 상태와 문구를 본다.
    def test_unsaved_store_is_stated_in_sync_step(self):
        with mock.patch.object(excel_store, "write_store", side_effect=excel_store.StoreError("열려 있음")):
            p = pipeline.Pipeline()
            p.run()
        self.assertEqual(p.state, "done")
        self.assertEqual(p.steps["sync"]["state"], "warning")
        self.assertIn("반영하지 못함", p.steps["sync"]["message"])

    # 목적: 예상하지 못한 오류로 끝나도 안내 문구에 다음에 할 일이 있고, 끝난 시각이 남는지 확인한다.
    # 이유: 오류 문구가 "중단했습니다"로 끝나 사용자가 무엇을 해야 할지 알 수 없었다(감사 A-16).
    # 방법: run이 예외를 내도록 바꿔 _run_safely를 부르고 상태와 문구, 결과의 error 키를 본다.
    def test_unexpected_error_message_tells_next_step(self):
        p = pipeline.Pipeline()
        with mock.patch.object(p, "run", side_effect=RuntimeError("boom")):
            p._run_safely()
        self.assertEqual(p.state, "failed")
        self.assertIn("다시 실행", p.current_message)
        self.assertIn("error", p.result)
        self.assertIsNotNone(p.finished_at)

    def test_offline_first_run_stops_cleanly(self):
        self.server.fail_times = 99
        p = pipeline.Pipeline()
        p.run()
        self.assertEqual(p.state, "failed")
        self.assertNotIn("candidates", p.result)
        self.assertEqual(p.steps["candidates"]["state"], "skipped")

    def test_offline_later_run_uses_existing_data(self):
        pipeline.Pipeline().run()
        self.server.fail_times = 99
        p = pipeline.Pipeline()
        p.run()
        self.assertEqual(p.state, "done")
        self.assertEqual(p.steps["sync"]["state"], "warning")
        self.assertEqual(len(p.result["candidates"]["numbers"]), 10)

    # 목적: 번호 재산출이 후보만 새로 고르고, 분석·백테스트 결과와 데이터는 그대로 두는지 확인한다.
    # 이유: 재산출 버튼은 전체 절차를 다시 돌리지 않는다고 화면에 밝힌다. 횟수 표시와 규칙 5의 모양도 지켜야 한다.
    # 방법: 한 번 돌린 뒤 두 번 재산출한다. 백테스트·분석 객체가 같은지, 후보가 10개·오름차순인지, 횟수가 1, 2로 느는지 본다.
    def test_redraw_replaces_only_candidates(self):
        p = pipeline.Pipeline()
        p.run()
        bt, an = p.result["backtest"], p.result["analysis"]
        self.assertEqual(p.result["candidates"]["redraw_count"], 0)
        for n in (1, 2):
            c = p.redraw()
            self.assertIs(p.result["candidates"], c)
            self.assertEqual(c["redraw_count"], n)
            self.assertEqual(len(set(c["numbers"])), 10)
            self.assertEqual(c["numbers"], sorted(c["numbers"]))
            self.assertEqual(c["target_round"], 131)
            self.assertIn(f"재산출 {n}번째", p.status()["steps"][4]["message"])
        self.assertIs(p.result["backtest"], bt)
        self.assertIs(p.result["analysis"], an)
        self.assertEqual(p.state, "done")

    # 목적: 실행 전이나 실행 중에는 재산출을 거부하고 다음에 할 일을 알려 주는지 확인한다.
    # 이유: 데이터가 없거나 결과가 반쯤 찬 상태에서 후보를 바꾸면 화면과 결과가 어긋난다.
    # 방법: 새 Pipeline과, 한 번 돌린 뒤 상태만 running으로 바꾼 Pipeline에서 redraw를 부른다.
    def test_redraw_refused_before_or_during_run(self):
        with self.assertRaises(pipeline.RedrawUnavailable) as ctx:
            pipeline.Pipeline().redraw()
        self.assertIn("다시 실행", str(ctx.exception))
        p = pipeline.Pipeline()
        p.run()
        p.state = "running"
        with self.assertRaises(pipeline.RedrawUnavailable) as ctx:
            p.redraw()
        self.assertIn("진행 중", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
