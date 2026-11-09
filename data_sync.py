# 목적: 시작할 때 전용 엑셀을 확인하고, 공식 데이터로 빠진 회차를 채우거나 틀린 회차를 바로잡는다.
# 사용처: pipeline.py의 첫 단계에서 한 번 부른다.
# 근거: 수집(collector)과 저장(excel_store)을 어떤 순서로 묶느냐가 "실패해도 원본 보존" 정책의 핵심이라 따로 둔다.

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import collector
import excel_store
from excel_loader import LottoDraw, check_sequence

OVERLAP_ROUNDS = 10  # 매번 최근 이만큼을 다시 받아 공식 값과 대조한다 (요청 1회 분량)


@dataclass
class SyncReport:
    status: str                      # created | updated | up_to_date | offline | failed
    draws: list[LottoDraw] = field(default_factory=list)
    added: list[int] = field(default_factory=list)
    corrected: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    removed: list[dict] = field(default_factory=list)  # 공식에 없어 지운 회차 {"round": n, "values": "..."}
    skipped_rows: list[dict] = field(default_factory=list)
    issues: dict = field(default_factory=dict)
    backup_path: Optional[str] = None
    saved: bool = False
    store_path: str = ""
    messages: list[str] = field(default_factory=list)

    @property
    def latest_round(self) -> int:
        return self.draws[-1].round_no if self.draws else 0


# 목적: 같은 회차의 두 기록이 같은지 비교한다.
# 이유: 공식 값과 다른 회차만 골라 수정 기록을 남겨야 한다.
# 방법: 번호 6개, 보너스, 추첨일을 비교한다. 기존 기록에 추첨일이 없으면 날짜는 비교하지 않는다.
def _differs(old: LottoDraw, new: LottoDraw) -> bool:
    if old.numbers != new.numbers or old.bonus != new.bonus:
        return True
    return bool(old.draw_date) and old.draw_date != new.draw_date


def _describe(d: LottoDraw) -> str:
    return f"{', '.join(str(n) for n in d.numbers)} + 보너스 {d.bonus}"


# 목적: 전용 엑셀을 공식 데이터 기준으로 최신 상태로 만든다.
# 이유: 실행할 때마다 최신 회차를 시도하되, 수집이나 저장이 실패해도 기존 정상 데이터는 그대로 두어야 한다.
# 방법: 1) 파일을 읽고 검증한다. 2) 빠진 회차·중복 회차·최근 10회 중 가장 이른 곳부터 공식 데이터를 받는다.
#       최근 10회는 1회부터 빠짐없이 이어진 마지막 회차 기준이라, 엑셀에 공식에 없는 큰 회차가 있어도 공식 최신을 확인한다.
#       3) 다른 회차는 공식 값으로 고치고 새 회차는 붙인다. 공식 최신보다 큰 회차는 공식에 없으므로 지우고 기록한다(W-11).
#       확인용으로 요청한 회차가 하나도 오지 않으면(빈 응답) "이미 최신"이 아니라 업데이트 실패로 본다(감사 A-04).
#       4) 바뀐 게 있을 때만 백업 → 임시 파일 저장 → 교체한다.
#       엑셀이 아직 없으면 수집 전에 데이터 폴더에 쓸 수 있는지 확인해, 못 쓰면 수집하지 않고 바로 안내한다.
#       시작할 때 이전 실행이 저장 중 종료되며 남긴 오래된 임시 파일도 함께 정리한다.
def sync(
    store_path: Optional[Path] = None,
    http_get: Optional[collector.HttpGet] = None,
    progress: Optional[Callable[[str], None]] = None,
    now: Optional[Callable[[], datetime]] = None,
    sleep: Optional[Callable[[float], None]] = None,
) -> SyncReport:
    path = store_path or (excel_store.data_dir() / excel_store.STORE_NAME)
    clock = now or datetime.now
    report = SyncReport(status="failed", store_path=str(path))
    say = progress or (lambda _msg: None)

    excel_store.cleanup_stale_temp(path.parent)
    existing: list[LottoDraw] = []
    log_rows: list[list] = []
    exists = path.exists()
    if exists:
        try:
            stored = excel_store.read_store(path)
        except excel_store.StoreError as exc:
            report.messages.append(str(exc))
            return report
        existing, log_rows = stored.draws, stored.log_rows
        report.skipped_rows = stored.skipped_rows
        for row in stored.skipped_rows:
            report.messages.append(f"엑셀 {row['row']}행을 건너뜀: {row['reason']}")

    else:
        try:
            excel_store.ensure_writable_dir(path.parent)
        except excel_store.StoreError as exc:
            report.messages.append(str(exc))
            return report

    by_round: dict[int, LottoDraw] = {}
    for d in existing:
        by_round.setdefault(d.round_no, d)  # 중복 회차는 첫 행을 남긴다
    seq = check_sequence(existing)

    contiguous = 0  # 1회부터 빠짐없이 이어진 마지막 회차
    while contiguous + 1 in by_round:
        contiguous += 1
    starts = [max(0, contiguous - OVERLAP_ROUNDS)]
    if seq["missing"]:
        starts.append(seq["missing"][0] - 1)
    if seq["duplicates"]:
        starts.append(seq["duplicates"][0] - 1)
    cursor = max(0, min(starts))

    say("공식 데이터 전체를 처음 받는 중입니다 (2~5분 걸립니다)" if not by_round else "공식 사이트에서 최신 회차를 확인하는 중입니다")
    try:
        fetched = collector.fetch_after(
            cursor, http_get=http_get, sleep=sleep,
            progress=lambda n: say(f"공식 데이터 수집 중: {n}회차까지 받음"),
        )
    except collector.CollectError as exc:
        report.draws = [by_round[n] for n in sorted(by_round)]
        report.issues = check_sequence(report.draws)
        report.status = "offline" if by_round else "failed"
        if by_round:
            report.messages.append(f"업데이트 실패: {exc} 기존 데이터({report.latest_round}회차까지)로 진행합니다.")
        else:
            report.messages.append(f"업데이트 실패: {exc} 분석할 데이터가 없어 진행할 수 없습니다.")
        return report

    if by_round and fetched.latest_seen == 0:
        report.draws = [by_round[n] for n in sorted(by_round)]
        report.issues = check_sequence(report.draws)
        report.status = "offline"
        report.messages.append(
            "업데이트 실패: 공식 사이트가 확인용으로 요청한 최근 회차를 하나도 돌려주지 않았습니다(빈 응답). "
            f"사이트가 바뀌었을 수 있습니다. 기존 데이터({report.latest_round}회차까지)로 진행하니, 잠시 뒤 다시 실행해 보세요.")
        return report

    report.rejected = fetched.rejected
    for r in fetched.rejected:
        report.messages.append(f"공식 응답 중 {r['round']}회차를 저장하지 않음: {r['reason']}")

    stamp = clock().strftime("%Y-%m-%d %H:%M:%S")
    new_logs: list[list] = []
    for d in fetched.draws:
        old = by_round.get(d.round_no)
        if old is None:
            report.added.append(d.round_no)
            if exists:
                new_logs.append([stamp, d.round_no, "추가", _describe(d)])
        elif _differs(old, d):
            report.corrected.append({"round": d.round_no, "before": _describe(old), "after": _describe(d)})
            new_logs.append([stamp, d.round_no, "공식 값으로 수정", f"{_describe(old)} → {_describe(d)}"])
        by_round[d.round_no] = d
    if not exists and report.added:
        new_logs.append([stamp, "", "생성", f"공식 데이터 1~{max(report.added)}회차로 새로 만듦"])
    for n in [n for n in sorted(by_round) if n > fetched.latest_seen]:
        gone = by_round.pop(n)
        report.removed.append({"round": n, "values": _describe(gone)})
        new_logs.append([stamp, n, "공식에 없는 회차 삭제", _describe(gone)])
        report.messages.append(
            f"엑셀의 {n}회차는 공식 사이트(최신 {fetched.latest_seen}회차)에 없어 분석에서 빼고 엑셀에서도 지웁니다. "
            "지우기 전 파일은 백업 폴더에 남깁니다.")

    merged = [by_round[n] for n in sorted(by_round)]
    report.draws = merged
    report.issues = check_sequence(merged)
    # 날짜가 없던 기존 행(예전 형식)에 공식 날짜만 채운 경우도 저장 대상이다
    filled_dates = any(old.draw_date is None and by_round[old.round_no].draw_date for old in existing)
    changed = bool(report.added or report.corrected or report.removed or seq["duplicates"] or report.skipped_rows
                   or filled_dates)

    if not merged:
        report.messages.append("공식 사이트에서 받은 회차가 없습니다. 사이트가 바뀌었을 수 있습니다.")
        return report

    if not changed:
        report.status = "up_to_date"
        report.saved = True
        return report

    try:
        if exists:
            report.backup_path = str(excel_store.backup_store(path, clock()))
        excel_store.write_store(path, merged, log_rows + new_logs)
        report.saved = True
    except excel_store.StoreError as exc:
        report.messages.append(f"엑셀 업데이트 실패: {exc} 이번 분석은 받은 공식 데이터로 진행하지만 파일에는 반영되지 않았습니다.")

    report.status = "created" if not exists else "updated"
    return report
