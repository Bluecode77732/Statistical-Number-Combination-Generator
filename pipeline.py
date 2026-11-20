# 목적: 시작 절차(업데이트 → 검증 → 분석 → 백테스트 → 후보 10개)를 순서대로 돌리고 진행 상태를 보관한다.
# 사용처: main.py가 /api/run에서 백그라운드로 시작하고, /api/status·/api/result에서 상태와 결과를 읽는다.
# 근거: 첫 실행은 수집에만 몇 분이 걸려 요청 한 번으로 끝낼 수 없다. 단계별 상태를 화면이 물어볼 곳이 필요하다.

from __future__ import annotations

import threading
import traceback
from datetime import datetime
from typing import Optional

import analysis
import backtest
import candidates
import data_sync
import excel_store

STEPS = [
    ("sync", "엑셀 확인 및 공식 데이터 업데이트"),
    ("validate", "데이터 검증"),
    ("analysis", "통계 분석"),
    ("backtest", "워크포워드 백테스트"),
    ("candidates", "후보 숫자 10개 생성"),
]


class RedrawUnavailable(Exception):
    """지금은 후보를 다시 고를 수 없을 때 발생. 메시지는 사용자에게 그대로 보여 준다."""


class Pipeline:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._reset()

    def _reset(self) -> None:
        self.state = "idle"  # idle | running | done | failed
        self.steps = {key: {"key": key, "label": label, "state": "pending", "message": ""} for key, label in STEPS}
        self.current_message = ""
        self.result: Optional[dict] = None
        self._draws: Optional[list] = None  # 마지막 실행이 후보를 만들 때 쓴 데이터 (재산출용)
        self._run_draws: Optional[list] = None  # 이번 실행이 수집 뒤 쓰는 데이터 (도중 오류 때 대체 후보용)
        self.started_at: Optional[str] = None
        self.finished_at: Optional[str] = None

    # 목적: 파이프라인을 백그라운드에서 시작한다.
    # 이유: 화면을 새로고침하거나 버튼을 여러 번 눌러도 동시에 두 번 돌지 않아야 한다.
    # 방법: 잠금 안에서 실행 중인지 보고, 아니면 상태를 초기화한 뒤 데몬 스레드로 run을 돌린다.
    def start(self) -> bool:
        with self._lock:
            if self.state == "running":
                return False
            self._reset()
            self.state = "running"
            self.started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._thread = threading.Thread(target=self._run_safely, daemon=True)
            self._thread.start()
            return True

    def status(self) -> dict:
        return {
            "state": self.state,
            "steps": [self.steps[key] for key, _ in STEPS],
            "message": self.current_message,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    def _step(self, key: str, state: str, message: str = "") -> None:
        self.steps[key]["state"] = state
        if message:
            self.steps[key]["message"] = message
        self.current_message = message or self.steps[key]["label"]

    def _say(self, key: str):
        return lambda msg: self._step(key, "running", msg)

    # 목적: run을 돌리고, 예상하지 못한 오류가 나도 실행 상태를 끝으로 바꾼다.
    # 이유: 스레드가 조용히 죽으면 화면이 "진행 중"에서 영원히 멈춘다. 예전에는 결과를 error 하나로 덮어써
    #       앞 단계 결과와 후보가 모두 사라졌다(감사 A-01, 핵심 규칙 10).
    # 방법: 모든 예외를 잡아 failed 상태와 다음에 할 일이 담긴 메시지로 바꾼다. 이미 끝난 단계의 결과는 그대로 두고
    #       error만 덧붙인다. 진행 중이던 단계는 failed, 남은 단계는 skipped로 바꾼다. 수집이 끝나 데이터가 있는데
    #       후보가 아직 없으면 무작위 대체 후보를 이유와 함께 넣는다. 끝난 시각은 항상 남긴다.
    def _run_safely(self) -> None:
        try:
            self.run()
        except Exception:  # noqa: BLE001 - 예상 못 한 오류도 화면에 남겨야 한다
            self.state = "failed"
            self.result = self.result or {}
            self.result["error"] = traceback.format_exc(limit=5)
            for step in self.steps.values():
                if step["state"] == "running":
                    step["state"], step["message"] = "failed", "예상하지 못한 오류로 멈춤"
                elif step["state"] == "pending":
                    step["state"], step["message"] = "skipped", "앞 단계 오류로 건너뜀"
            replaced = False
            if "candidates" not in self.result and self._run_draws:
                cand = candidates.fallback_candidates(
                    self._run_draws, "분석 도중 예상하지 못한 오류가 나서 무작위로 대체했습니다.")
                cand["redraw_count"] = 0
                self.result["candidates"] = cand
                self._draws = self._run_draws
                self.steps["candidates"]["state"] = "warning"
                self.steps["candidates"]["message"] = f"{cand['target_round']}회차용 · {cand['method_label']}"
                replaced = True
            self.current_message = (
                "예상하지 못한 오류로 중단했습니다. 끝난 단계의 결과는 남겨 두었습니다"
                + (" (후보는 무작위로 대체)" if replaced else "")
                + ". 프로그램을 닫고 다시 실행해 보세요.")
        finally:
            self.finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 목적: 시작 절차의 각 단계를 실행하고 결과를 한 덩어리로 모은다.
    # 이유: 업데이트나 백테스트가 실패해도, 가능한 범위의 결과(기존 데이터 분석, 무작위 대체 후보)는 보여 줘야 한다.
    # 방법: 업데이트 실패 중 데이터가 아예 없는 경우만 중단하고, 나머지 실패는 상태와 메시지로 남긴 채 다음 단계로 간다.
    #       저장하지 못했거나 건너뛴 엑셀 행이 있으면 단계 문구에도 밝혀, "업데이트함"·"이상 없음"으로 오해하지 않게 한다.
    #       후보를 만든 데이터는 재산출(redraw)이 같은 데이터로 다시 고를 수 있게 보관한다. 수집 직후의 데이터는
    #       도중에 예상하지 못한 오류가 나도 _run_safely가 대체 후보를 낼 수 있게 따로 둔다.
    #       공식에 없어 지운 회차(removed)도 수집 결과에 담아 화면이 알릴 수 있게 한다.
    def run(self) -> None:
        self._step("sync", "running")
        report = data_sync.sync(progress=self._say("sync"))
        sync_info = {
            "status": report.status, "store_path": report.store_path, "latest_round": report.latest_round,
            "first_round": report.draws[0].round_no if report.draws else 0,
            "first_date": report.draws[0].draw_date if report.draws else None,
            "latest_date": report.draws[-1].draw_date if report.draws else None,
            "added": report.added, "corrected": report.corrected, "rejected": report.rejected, "removed": report.removed,
            "backup_path": report.backup_path, "saved": report.saved, "messages": report.messages,
        }
        sync_labels = {"created": "새로 만듦", "updated": "업데이트함", "up_to_date": "이미 최신",
                       "offline": "업데이트 실패 — 기존 데이터 사용", "failed": "실패"}
        sync_state = "warning" if report.status == "offline" or (report.status != "failed" and not report.saved) else (
            "failed" if report.status == "failed" else "done")
        unsaved = " — 엑셀 파일에는 반영하지 못함" if report.status in ("created", "updated") and not report.saved else ""
        self._step("sync", sync_state, f"{sync_labels[report.status]} (확인된 최신 {report.latest_round}회차){unsaved}")
        self.result = {"sync": sync_info}
        if report.status == "failed":
            for key in ("validate", "analysis", "backtest", "candidates"):
                self._step(key, "skipped", "데이터가 없어 건너뜀")
            self.state = "failed"
            self.current_message = report.messages[-1] if report.messages else "데이터를 준비하지 못했습니다."
            return

        draws = report.draws
        self._run_draws = draws
        self._step("validate", "running")
        issues = report.issues
        problems = []
        if issues.get("missing"):
            problems.append(f"빠진 회차 {len(issues['missing'])}개: {issues['missing'][:10]}")
        if issues.get("duplicates"):
            problems.append(f"중복 회차: {issues['duplicates'][:10]}")
        if report.skipped_rows:
            problems.append(f"건너뛴 엑셀 행 {len(report.skipped_rows)}개 (사유는 데이터 영역의 알림 참고)")
        self.result["validation"] = {"rounds": len(draws), "missing": issues.get("missing", []),
                                     "duplicates": issues.get("duplicates", []),
                                     "skipped_rows": report.skipped_rows}
        self._step("validate", "warning" if problems else "done",
                   "; ".join(problems) if problems else f"{len(draws)}개 회차 이상 없음")

        self._step("analysis", "running")
        self.result["analysis"] = analysis.run_all(draws)
        failed_items = [a["title"] for a in self.result["analysis"] if "error" in a]
        self._step("analysis", "warning" if failed_items else "done",
                   f"실패 항목: {', '.join(failed_items)}" if failed_items else "9개 항목 완료")

        self._step("backtest", "running")
        bt = backtest.run_backtest(draws, progress=self._say("backtest"))
        self.result["backtest"] = bt
        if bt.get("ran"):
            try:
                path = excel_store.data_dir() / excel_store.BACKTEST_NAME
                excel_store.write_backtest(path, bt)
                bt["saved_path"] = str(path)
            except excel_store.StoreError as exc:
                bt["save_error"] = str(exc)
            msg = f"{bt['start_round']}~{bt['end_round']}회 ({bt['rounds']}회) {bt['seconds']}초"
            self._step("backtest", "warning" if bt.get("save_error") or bt["model_errors"] else "done", msg)
        else:
            self._step("backtest", "warning", bt.get("message", "백테스트를 하지 못했습니다."))

        self._step("candidates", "running")
        cand = candidates.next_candidates(draws)
        cand["redraw_count"] = 0
        self.result["candidates"] = cand
        self._draws = draws
        self._step("candidates", "warning" if cand["method"] == "random" else "done",
                   f"{cand['target_round']}회차용 · {cand['method_label']}")
        self.state = "done"
        self.current_message = "완료"

    # 목적: 마지막 실행의 데이터로 후보 10개만 재산출 규칙으로 새로 고른다.
    # 이유: 수집·분석·백테스트(약 12초)를 다시 하지 않고 새 한 세트를 보게 한다(사용자 요청, 2026-11-09).
    #       2026-11-20 사용자 결정으로 재산출은 첫 산출(점수 상위 10개)과 다른 규칙(점수 5 · 최근 5회 2 · 빈도 3)을 쓴다.
    #       고르는 코드는 백테스트가 재산출 규칙을 잴 때와 같은 mixed_candidates다.
    # 방법: 잠금 안에서 실행 중이거나 후보를 만든 실행이 없으면 RedrawUnavailable을 낸다. 아니면 redraw_candidates를
    #       불러 결과의 후보만 바꾸고 재산출 횟수를 1 늘린다. 다른 결과(분석, 백테스트)와 진행 상태 문구는 그대로 둔다.
    def redraw(self) -> dict:
        with self._lock:
            if self.state == "running":
                raise RedrawUnavailable("분석이 진행 중입니다. 끝난 뒤 다시 눌러 주세요.")
            if self._draws is None or not self.result or "candidates" not in self.result:
                raise RedrawUnavailable("아직 후보를 만든 실행이 없습니다. '다시 실행'으로 분석을 먼저 끝내 주세요.")
            count = self.result["candidates"].get("redraw_count", 0) + 1
            cand = candidates.redraw_candidates(self._draws)
            cand["redraw_count"] = count
            self.result["candidates"] = cand
            self.steps["candidates"]["state"] = "warning" if cand["method"] == "random" else "done"
            self.steps["candidates"]["message"] = (
                f"{cand['target_round']}회차용 · {cand['method_label']} · 재산출 {count}번째")
            return cand
