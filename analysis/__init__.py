# 목적: 분석 항목 9개를 한곳에 등록하고 한 번에 실행한다.
# 사용처: pipeline.py가 run_all을 부른다. 항목 모듈끼리는 서로 import하지 않는다.
# 근거: "각 분석 항목은 독립 모듈"이라는 요구에 맞춰, 항목을 더하거나 빼도 다른 항목이 영향받지 않게 등록만 여기서 한다.

from __future__ import annotations

from excel_loader import LottoDraw

from . import (
    consecutive,
    frequency,
    gaps,
    last_digit,
    odd_even,
    repeats,
    sections,
    structure,
    sums,
)

MODULES = [frequency, odd_even, sections, consecutive, sums, gaps, last_digit, repeats, structure]


# 목적: 모든 분석 항목을 실행해 화면에 보낼 목록을 만든다.
# 이유: 한 항목이 실패해도 나머지 결과는 보여 줘야 한다.
# 방법: 항목마다 따로 실행하고, 예외가 나면 그 항목만 오류 메시지로 채운다.
def run_all(draws: list[LottoDraw]) -> list[dict]:
    results = []
    for module in MODULES:
        item = {"key": module.KEY, "title": module.TITLE, "method": module.METHOD}
        try:
            item["result"] = module.compute(draws)
        except Exception as exc:  # noqa: BLE001 - 항목 하나의 실패가 전체 분석을 막지 않게 한다
            item["error"] = f"계산 실패: {exc}"
        results.append(item)
    return results
