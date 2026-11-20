# 목적: 프로그램이 관리하는 전용 엑셀(data\lotto.xlsx)과 백테스트 결과 엑셀을 읽고 쓴다.
# 사용처: data_sync.py가 당첨번호를 읽고 저장할 때, pipeline.py가 백테스트 결과를 남길 때 부른다.
# 근거: 쓰기·백업·교체 실패 처리를 한 곳에 모아야, 수집이나 분석 코드가 원본을 망가뜨릴 길이 없어진다.

from __future__ import annotations

import filecmp
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from openpyxl import Workbook, load_workbook

from excel_loader import ExcelValidationError, LottoDraw, load_excel

DRAW_SHEET = "당첨번호"
LOG_SHEET = "변경기록"
DRAW_HEADER = ["회차", "추첨일", "번호1", "번호2", "번호3", "번호4", "번호5", "번호6", "보너스번호"]
LOG_HEADER = ["시각", "회차", "구분", "내용"]
BACKUP_KEEP = 10
STORE_NAME = "lotto.xlsx"
BACKTEST_NAME = "backtest.xlsx"
STALE_TEMP_SECONDS = 3600  # 이보다 오래 남은 저장용 임시 파일은 이전 실행의 잔여물로 본다


class StoreError(Exception):
    """전용 엑셀을 읽거나 쓸 수 없을 때 발생. 메시지는 사용자에게 그대로 보여 준다."""


@dataclass
class StoredData:
    draws: list[LottoDraw]
    skipped_rows: list[dict] = field(default_factory=list)
    log_rows: list[list] = field(default_factory=list)


# 목적: 데이터 폴더 위치를 정한다.
# 이유: 실행 파일로 배포하면 앱 파일과 데이터를 분리해야 업데이트 때 데이터가 지워지지 않는다.
# 방법: LOTTO_DATA_DIR 환경 변수가 있으면 그곳, 실행 파일이면 exe 옆 data, 개발 중이면 프로젝트의 data를 쓴다.
def data_dir() -> Path:
    override = os.environ.get("LOTTO_DATA_DIR")
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "data"
    return Path(__file__).resolve().parent / "data"


# 목적: 폴더를 만들 수 있는지, 그 안에 파일을 쓸 수 있는지 미리 확인한다.
# 이유: 쓸 수 없는 폴더(Program Files 등)에서는 2~5분 수집을 마친 뒤에야 저장이 실패하므로, 시작할 때 알려야 한다.
# 방법: 폴더를 만들고 작은 임시 파일을 써 본 뒤 지운다. 실패하면 StoreError에 다음에 할 일을 담는다.
def ensure_writable_dir(folder: Path) -> None:
    probe = folder / f".write-test-{os.getpid()}"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe.write_bytes(b"")
    except OSError as exc:
        raise StoreError(
            f"데이터를 저장할 폴더를 만들거나 쓸 수 없습니다: {folder} "
            "바탕화면이나 문서 폴더처럼 쓰기 권한이 있는 곳에 압축을 풀어 다시 실행해 주세요."
        ) from exc
    finally:
        _remove_quietly(probe)


# 목적: 전용 엑셀의 당첨번호와 변경기록을 읽는다.
# 이유: 업데이트 전에 기존 데이터를 검증하고, 다시 쓸 때 변경기록을 잃지 않아야 한다.
# 방법: 당첨번호는 기존 검증 로더(load_excel)로 읽고, 변경기록 시트는 openpyxl로 그대로 읽는다.
def read_store(path: Path) -> StoredData:
    try:
        data = path.read_bytes()
    except PermissionError as exc:
        raise StoreError(f"엑셀 파일을 열 수 없습니다. 다른 프로그램이 쓰고 있다면 닫아 주세요: {path}") from exc
    except OSError as exc:
        raise StoreError(
            f"엑셀 파일을 읽지 못했습니다: {exc} 파일 위치와 권한을 확인한 뒤 다시 실행해 주세요."
        ) from exc

    try:
        loaded = load_excel(data)
    except ExcelValidationError as exc:
        raise StoreError(
            f"전용 엑셀이 손상되었거나 형식이 다릅니다({exc}). "
            f"파일을 다른 곳으로 옮기면 공식 데이터로 새로 만듭니다: {path}"
        ) from exc

    log_rows: list[list] = []
    try:
        wb = load_workbook(path, read_only=True)
        if LOG_SHEET in wb.sheetnames:
            rows = list(wb[LOG_SHEET].iter_rows(values_only=True))
            log_rows = [list(r) for r in rows[1:] if any(v is not None for v in r)]
        wb.close()
    except Exception:  # noqa: BLE001 - 변경기록은 부가 정보라 못 읽어도 당첨번호 처리는 계속한다
        log_rows = []

    return StoredData(draws=loaded.draws, skipped_rows=loaded.skipped_rows, log_rows=log_rows)


# 목적: 바꾸기 직전의 엑셀을 백업 폴더에 복사한다.
# 이유: 업데이트가 잘못돼도 직전 상태로 되돌릴 수 있어야 한다. 오래된 백업 정리는 저장에 성공한 뒤
#       prune_backups가 따로 한다(감사 A-11: 저장이 계속 실패하면 같은 내용의 백업이 이전 복원 지점을 밀어냈다).
# 방법: data\backup\lotto_YYYYMMDD_HHMMSS.xlsx로 복사한다. 이름이 겹치면 _1, _2를 붙인다.
#       백업 폴더를 만들지 못하는 경우도 처리되지 않은 오류가 아니라 StoreError로 알린다.
def backup_store(path: Path, now: Optional[datetime] = None) -> Path:
    backup_dir = path.parent / "backup"
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise StoreError(f"백업 폴더를 만들지 못해 업데이트를 중단했습니다: {exc}") from exc
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    target = backup_dir / f"{path.stem}_{stamp}{path.suffix}"
    counter = 1
    while target.exists():
        target = backup_dir / f"{path.stem}_{stamp}_{counter}{path.suffix}"
        counter += 1
    try:
        shutil.copy2(path, target)
    except OSError as exc:
        raise StoreError(f"백업을 만들지 못해 업데이트를 중단했습니다: {exc}") from exc
    return target


# 목적: 백업 폴더에 최근 BACKUP_KEEP개만 남긴다.
# 이유: 실행마다 백업이 쌓이면 안 되지만, 저장이 실패한 실행에서 지우면 이전 복원 지점을 잃는다(감사 A-11).
# 방법: 저장에 성공한 뒤에만 부른다. 이름순(=시간순)으로 정렬해 오래된 것부터 지우고, 못 지우면 다음 실행에 맡긴다.
def prune_backups(path: Path) -> None:
    backup_dir = path.parent / "backup"
    try:
        backups = sorted(backup_dir.glob(f"{path.stem}_*{path.suffix}"))
    except OSError:
        return
    for old in backups[:-BACKUP_KEEP]:
        try:
            old.unlink()
        except OSError:
            pass  # 지우지 못한 오래된 백업은 다음 실행 때 다시 시도한다


# 목적: 저장이 실패한 실행에서 방금 만든 백업을 거둔다.
# 이유: 저장이 실패하면 원본이 그대로라 그 백업은 원본과 같은 사본이다. 실패가 반복될 때 같은 사본이
#       쌓여 다음 성공 때 이전 복원 지점이 밀려나지 않게 한다(감사 A-11).
# 방법: 백업과 원본을 바이트 단위로 비교해 같을 때만 지운다. 다르거나 비교할 수 없으면 백업을 남긴다.
def discard_backup_if_unchanged(path: Path, backup: Path) -> bool:
    try:
        if not filecmp.cmp(path, backup, shallow=False):
            return False
        backup.unlink()
    except OSError:
        return False
    return True


# 목적: 워크북을 원본을 해치지 않는 방식으로 저장한다.
# 이유: 저장 도중 실패(디스크, 전원, 열린 파일)하면 원본이 반쯤 쓰인 채 남을 수 있다.
# 방법: 같은 폴더의 임시 파일에 먼저 저장하고 os.replace로 바꿔치기한다. 실패하면 임시 파일만 지운다.
#       폴더를 만들 수 없는 경우도 StoreError로 바꿔, 호출한 쪽이 한글 안내를 화면에 낼 수 있게 한다.
def _save_atomic(wb: Workbook, path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise StoreError(f"데이터 폴더를 만들지 못했습니다: {path.parent} ({exc})") from exc
    tmp = path.with_name(f".{path.stem}.tmp-{os.getpid()}{path.suffix}")
    try:
        wb.save(tmp)
        os.replace(tmp, path)
    except PermissionError as exc:
        _remove_quietly(tmp)
        raise StoreError(
            f"엑셀 파일이 다른 프로그램(Excel 등)에서 열려 있어 저장하지 못했습니다. 닫고 다시 실행해 주세요: {path}"
        ) from exc
    except OSError as exc:
        _remove_quietly(tmp)
        raise StoreError(
            f"엑셀 파일을 저장하지 못했습니다: {exc} 디스크 공간과 폴더 쓰기 권한을 확인한 뒤 다시 실행해 주세요."
        ) from exc


def _remove_quietly(p: Path) -> None:
    try:
        p.unlink()
    except OSError:
        pass


# 목적: 이전 실행이 저장 도중 강제 종료되어 남긴 임시 파일(.lotto.tmp-..., .backtest.tmp-...)을 지운다.
# 이유: 저장 중 종료되면 _save_atomic이 정리하지 못해 데이터 폴더에 임시 파일이 쌓일 수 있다.
# 방법: 앱이 만드는 이름 형식만 찾아 마지막 수정 후 STALE_TEMP_SECONDS가 지난 것만 지운다. 다른 실행기가
#       저장 중인 파일은 건드리지 않으며, 지우지 못해도 오류 없이 넘어가고 지운 파일 이름을 돌려준다.
def cleanup_stale_temp(folder: Path, now: Optional[float] = None) -> list[str]:
    current = time.time() if now is None else now
    removed: list[str] = []
    for name in (STORE_NAME, BACKTEST_NAME):
        pattern = f".{Path(name).stem}.tmp-*{Path(name).suffix}"
        try:
            candidates = list(folder.glob(pattern))
        except OSError:
            continue
        for tmp in candidates:
            try:
                if tmp.is_file() and current - tmp.stat().st_mtime > STALE_TEMP_SECONDS:
                    tmp.unlink()
                    removed.append(tmp.name)
            except OSError:
                pass  # 지우지 못한 파일은 다음 실행 때 다시 시도한다
    return removed


# 목적: 당첨번호 전체와 변경기록을 전용 엑셀로 저장한다.
# 이유: 장기 저장소는 이 엑셀 하나뿐이라, 매 저장이 완전한 상태여야 한다.
# 방법: 회차순으로 당첨번호 시트를 새로 쓰고, 변경기록 시트에 기존 기록과 새 기록을 이어 붙여 원자적으로 저장한다.
def write_store(path: Path, draws: list[LottoDraw], log_rows: list[list]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = DRAW_SHEET
    ws.append(DRAW_HEADER)
    for d in sorted(draws, key=lambda x: x.round_no):
        ws.append([d.round_no, d.draw_date or "", *d.numbers, d.bonus])
    ws.freeze_panes = "A2"

    log = wb.create_sheet(LOG_SHEET)
    log.append(LOG_HEADER)
    for row in log_rows:
        log.append(list(row))

    _save_atomic(wb, path)


# 목적: 백테스트의 예측과 실제 결과를 별도 엑셀로 남긴다.
# 이유: 예측과 실제를 섞지 않고 따로 보관하라는 요구가 있고, 화면을 닫은 뒤에도 확인할 수 있어야 한다.
#       2026-11-20부터 두 선택 방식(첫 화면, 재산출 규칙)을 함께 재므로 요약에 z와 직전 회차 포함 평균을 더했다.
# 방법: 예측·실제·요약 시트를 나눠 실행마다 새로 쓴다. 당첨번호 엑셀과는 다른 파일이라 백업 대상이 아니다.
#       예측 시트는 방식마다 한 행씩, "모델" 열에 방식 이름을 쓴다.
def write_backtest(path: Path, result: dict) -> None:
    wb = Workbook()
    pred = wb.active
    pred.title = "예측"
    pred.append(["회차", "모델", *[f"후보{i}" for i in range(1, 11)]])
    actual = wb.create_sheet("실제")
    actual.append(["회차", "번호1", "번호2", "번호3", "번호4", "번호5", "번호6", "보너스번호"])
    for p in result["predictions"]:
        pred.append([p["round"], p["model_label"], *p["candidates"]])
    for a in result["actuals"]:
        actual.append([a["round"], *a["numbers"], a["bonus"]])

    summary = wb.create_sheet("요약")
    summary.append(["모델", "시험 회차 수", "평균 일치 개수", "95% 범위 하한", "95% 범위 상한", "z", "판정",
                    "직전 회차 번호 포함 평균"])
    for s in result["summaries"]:
        summary.append([s["label"], s["rounds"], s["mean"], s["ci_low"], s["ci_high"], s["z"], s["verdict"],
                        s["prev_overlap_mean"]])
    summary.append([])
    summary.append(["무작위 이론값", "", result["theory"]["mean"], "", "", "", "10×6/45", result["theory"]["mean"]])
    _save_atomic(wb, path)
