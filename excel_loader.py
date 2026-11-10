"""
Excel 파일 읽기 및 데이터 검증 (Excel Loader & Validator)

프로그램이 관리하는 전용 엑셀(data 폴더의 lotto.xlsx)의 당첨번호 시트를 pandas로 읽어
1회차부터 최신 회차까지의 데이터를 파싱하고 형식을 검증한다.

이 모듈은 데이터를 읽고 검증하는 역할만 담당한다.
전용 엑셀(excel_store.py)과 공식 데이터 수집(collector.py)이 같은 검증 규칙을 쓴다.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import pandas as pd

MIN_NUM = 1
MAX_NUM = 45
NUMBER_COUNT = 6

# 전용 엑셀(excel_store.DRAW_HEADER)의 제목 행 이름. 앞뒤 공백만 무시하고 그대로 찾는다.
ROUND_COL = "회차"
NUMBER_COLS = [f"번호{i}" for i in range(1, NUMBER_COUNT + 1)]
BONUS_COL = "보너스번호"
DATE_COL = "추첨일"


class ExcelValidationError(Exception):
    """필수 컬럼이 없거나 파일 자체를 읽을 수 없거나, 유효한 데이터가 없을 때 발생."""


@dataclass
class LottoDraw:
    round_no: int
    numbers: list[int]
    bonus: Optional[int] = None
    draw_date: Optional[str] = None  # YYYY-MM-DD


@dataclass
class LoadResult:
    draws: list[LottoDraw]
    skipped_rows: list[dict] = field(default_factory=list)


# 목적: 전용 엑셀의 당첨번호 시트를 검증된 회차 목록으로 바꾼다.
# 이유: 분석과 수집 비교 전에 형식 오류를 걸러 낸다. 앱은 전용 엑셀만 읽으므로 제목 행 없는 파일과
#       컬럼 별칭 읽기는 지웠다(결정 D-5, 감사 A-17).
# 방법: 제목 행의 '회차', '번호1'~'번호6'을 이름으로 찾고 행 단위로 검증한다.
#       회차가 1 미만이거나, 보너스가 범위 밖이거나 당첨번호와 겹치거나, 추첨일이 달력에 없는 날짜인 행도 건너뛴다.
#       보너스·추첨일 칸이 비어 있는 것은 옛 형식으로 보고 허용한다.
def load_excel(file_bytes: bytes) -> LoadResult:
    """
    Excel 바이트 데이터를 읽어 검증된 LottoDraw 목록을 반환한다.
    형식이 잘못된 파일이면 ExcelValidationError를 발생시킨다.
    """
    try:
        df = pd.read_excel(io.BytesIO(file_bytes))
    except Exception as exc:  # noqa: BLE001 - 사용자에게 원인을 그대로 알려주기 위함
        raise ExcelValidationError(f"Excel 파일을 읽는 중 오류가 발생했습니다: {exc}") from exc

    if df.empty:
        raise ExcelValidationError("Excel 파일에 데이터가 없습니다.")

    df.columns = [str(c).strip() for c in df.columns]
    missing = [c for c in [ROUND_COL, *NUMBER_COLS] if c not in df.columns]
    if missing:
        raise ExcelValidationError(f"제목 행에 {', '.join(missing)} 컬럼이 없습니다.")

    row_offset = 2  # 1행은 제목 행이므로 인덱스 0이 엑셀 2행
    round_col = ROUND_COL
    number_cols = NUMBER_COLS
    bonus_col = BONUS_COL if BONUS_COL in df.columns else None
    date_col = DATE_COL if DATE_COL in df.columns else None

    draws: list[LottoDraw] = []
    skipped_rows: list[dict] = []

    for idx, row in df.iterrows():
        excel_row_no = int(idx) + row_offset

        round_no = _safe_int(row[round_col])
        if round_no is None or round_no < 1:
            skipped_rows.append({"row": excel_row_no, "reason": "회차는 1 이상의 정수여야 합니다."})
            continue

        numbers: list[int] = []
        invalid = False
        for c in number_cols:
            n = _safe_int(row[c])
            if n is None:
                skipped_rows.append({"row": excel_row_no, "reason": "번호 값 중 정수가 아닌 값이 있습니다."})
                invalid = True
                break
            numbers.append(n)
        if invalid:
            continue

        if any(n < MIN_NUM or n > MAX_NUM for n in numbers):
            skipped_rows.append(
                {"row": excel_row_no, "reason": f"번호는 {MIN_NUM}~{MAX_NUM} 범위여야 합니다."}
            )
            continue

        if len(set(numbers)) != NUMBER_COUNT:
            skipped_rows.append({"row": excel_row_no, "reason": "같은 회차 내에 중복된 번호가 있습니다."})
            continue

        bonus = None
        if bonus_col is not None and not _is_blank(row[bonus_col]):
            bonus = _safe_int(row[bonus_col])
            if bonus is None or not MIN_NUM <= bonus <= MAX_NUM:
                skipped_rows.append(
                    {"row": excel_row_no, "reason": f"보너스 번호는 {MIN_NUM}~{MAX_NUM} 범위의 정수여야 합니다."}
                )
                continue
        if bonus is not None and bonus in numbers:
            skipped_rows.append({"row": excel_row_no, "reason": "보너스 번호가 당첨 번호와 겹칩니다."})
            continue

        draw_date = None
        if date_col is not None and not _is_blank(row[date_col]):
            draw_date = str(row[date_col]).strip()[:10]
            if not _is_valid_date(draw_date):
                skipped_rows.append({"row": excel_row_no, "reason": "추첨일이 YYYY-MM-DD 형식의 실제 날짜가 아닙니다."})
                continue

        draws.append(
            LottoDraw(round_no=round_no, numbers=sorted(numbers), bonus=bonus, draw_date=draw_date)
        )

    if not draws:
        raise ExcelValidationError(
            "유효한 데이터 행이 하나도 없습니다. 컬럼 형식과 데이터 내용을 확인하세요."
        )

    draws.sort(key=lambda d: d.round_no)  # 1회차 -> 최신 회차 순 정렬

    return LoadResult(draws=draws, skipped_rows=skipped_rows)


# 목적: 회차 목록 전체에서 행 단위 검사로는 못 잡는 문제(회차 중복, 빠진 회차)를 찾는다.
# 이유: 자동 업데이트가 "마지막 회차 다음부터" 받기 때문에, 중간이 비거나 겹치면 분석과 수집이 모두 어긋난다.
# 방법: 회차 번호를 세어 2번 이상 나온 것과, 1부터 최대 회차까지 중 없는 것을 돌려준다.
def check_sequence(draws: list[LottoDraw]) -> dict[str, list[int]]:
    seen: dict[int, int] = {}
    for d in draws:
        seen[d.round_no] = seen.get(d.round_no, 0) + 1
    duplicates = sorted(n for n, c in seen.items() if c > 1)
    last = max(seen) if seen else 0
    missing = [n for n in range(1, last + 1) if n not in seen]
    return {"duplicates": duplicates, "missing": missing}


def _is_blank(value) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


# 목적: 엑셀 칸의 값을 정수로 읽고, 정수가 아니면 None을 돌려준다.
# 이유: 1.9를 1로 잘라 읽으면 잘못된 번호가 조용히 통과해 분석과 저장에 섞여 들어간다(감사 A-10).
# 방법: 실수는 정수와 같을 때만 받는다(엑셀이 5를 5.0으로 줄 수 있다). 비어 있거나 불리언이거나 숫자가 아니면 None이다.
def _safe_int(value) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return int(number) if number.is_integer() else None


# 목적: 문자열이 YYYY-MM-DD 형식의 실제 달력 날짜인지 확인한다.
# 이유: 형식만 보고 받으면 2026-13-99 같은 날짜가 전용 엑셀에 저장된다(감사 A-10).
# 방법: strptime으로 읽어 보고, 자릿수가 다른 값(2026-1-5)은 따로 거른다.
def _is_valid_date(text: str) -> bool:
    if len(text) != 10:
        return False
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return False
    return True
