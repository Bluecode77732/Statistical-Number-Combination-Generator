"""
과거 데이터 분석 모듈 (Historical Data Analyzer)

** 금지 사항 (이 프로젝트의 핵심 규칙) **
- 번호별(1~45 개별 번호) 출현 빈도는 계산하지 않는다.
- 번호별 점수, 조합 점수, 확률 점수, 가중치, 순위를 만들지 않는다.
- 이 모듈의 결과는 오직 화면 표시용이며, generator.py로 전달되지 않는다.
  (실제로 이 모듈은 generator.py를 import하지 않고, generator.py도 이
  모듈을 import하지 않는다 — 코드 레벨에서 서로 완전히 독립적이다.)

여기서 계산하는 것은 "회차 단위" 통계(각 회차 6개 번호의 합, 홀짝 개수,
고저 개수, 연속번호 여부 등)와, 순수 무작위 선택이 과거 회차와 비교해
평균적으로 몇 개나 맞는지를 보여주는 백테스트뿐이다. 이는 개별 번호에
대한 점수/가중치가 아니라, "로또는 완전히 무작위"라는 사실을 보여주는
참고용 통계다.
"""

from __future__ import annotations

import random
import statistics
from typing import TypedDict

from excel_loader import LottoDraw

LOTTO_MIN = 1
LOTTO_MAX = 45
PICK_COUNT = 6
LOW_HIGH_BOUNDARY = 22  # 1~22 저구간, 23~45 고구간


class SumStats(TypedDict):
    min: int
    max: int
    avg: float
    median: float


class AnalysisResult(TypedDict):
    total_rounds: int
    first_round: int
    last_round: int
    sum_stats: SumStats
    odd_count_distribution: dict[str, int]
    high_count_distribution: dict[str, int]
    consecutive_pair_ratio: dict[str, float | int]


class BacktestResult(TypedDict):
    simulated_rounds: int
    match_distribution: dict[str, int]
    average_matches: float
    theoretical_average_matches: float
    note: str


def analyze(draws: list[LottoDraw]) -> AnalysisResult:
    """회차 단위 집계 통계만 계산한다. 개별 번호 빈도는 다루지 않는다."""
    sums = [sum(d.numbers) for d in draws]
    odd_counts = [sum(1 for n in d.numbers if n % 2 == 1) for d in draws]
    high_counts = [sum(1 for n in d.numbers if n > LOW_HIGH_BOUNDARY) for d in draws]
    consecutive_flags = [_has_consecutive(d.numbers) for d in draws]

    odd_distribution = {str(i): 0 for i in range(PICK_COUNT + 1)}
    for c in odd_counts:
        odd_distribution[str(c)] += 1

    high_distribution = {str(i): 0 for i in range(PICK_COUNT + 1)}
    for c in high_counts:
        high_distribution[str(c)] += 1

    with_consecutive = sum(1 for f in consecutive_flags if f)
    total = len(draws)

    return {
        "total_rounds": total,
        "first_round": draws[0].round_no,
        "last_round": draws[-1].round_no,
        "sum_stats": {
            "min": min(sums),
            "max": max(sums),
            "avg": round(statistics.mean(sums), 2),
            "median": statistics.median(sums),
        },
        "odd_count_distribution": odd_distribution,
        "high_count_distribution": high_distribution,
        "consecutive_pair_ratio": {
            "with_consecutive": with_consecutive,
            "without_consecutive": total - with_consecutive,
            "percentage": round(with_consecutive / total * 100, 1) if total else 0.0,
        },
    }


def backtest(draws: list[LottoDraw]) -> BacktestResult:
    """
    각 과거 회차에 대해, 그 회차와는 무관한 순수 무작위 6개 번호를
    한 번씩 뽑아 실제 당첨 번호와 몇 개나 일치하는지 집계한다.

    이 시뮬레이션은 "무작위 선택은 특별한 전략 없이도 이 정도 성능을
    보인다"는 것을 보여주는 참고 자료일 뿐이며, 그 결과가 실제 번호
    생성기(generator.py)에 어떤 형태로도 반영되지 않는다.
    """
    rng = random.Random()  # generator.py의 RNG와 완전히 별개의 인스턴스
    match_counts = {str(i): 0 for i in range(PICK_COUNT + 1)}

    for d in draws:
        guess = set(rng.sample(range(LOTTO_MIN, LOTTO_MAX + 1), PICK_COUNT))
        matches = len(guess & set(d.numbers))
        match_counts[str(matches)] += 1

    total = len(draws)
    average_matches = sum(int(k) * v for k, v in match_counts.items()) / total if total else 0.0

    return {
        "simulated_rounds": total,
        "match_distribution": match_counts,
        "average_matches": round(average_matches, 3),
        "theoretical_average_matches": round(PICK_COUNT * PICK_COUNT / LOTTO_MAX, 3),
        "note": (
            "각 회차마다 해당 회차와 무관한 순수 무작위 6개 번호를 1회 뽑아 "
            "실제 당첨 번호와 일치 개수를 비교한 결과입니다. 평균 일치 개수가 "
            "이론적 기댓값(6×6/45)에 가깝다는 것은, 과거 데이터에 어떤 패턴을 "
            "적용해도 무작위 선택 이상의 이득을 기대하기 어렵다는 것을 보여줍니다."
        ),
    }


def _has_consecutive(numbers: list[int]) -> bool:
    s = sorted(numbers)
    return any(b - a == 1 for a, b in zip(s, s[1:]))
