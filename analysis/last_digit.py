# 목적: 당첨번호의 끝자리(0~9) 패턴을 집계한다.
# 사용처: analysis.run_all이 부른다.
# 근거: 요구된 분석 항목 7번. 다른 항목과 독립적으로 바꿀 수 있게 따로 둔다.

from __future__ import annotations

KEY = "last_digit"
TITLE = "끝자리 패턴"
METHOD = (
    "모든 당첨번호의 끝자리(번호 ÷ 10의 나머지)별 출현 수와, 회차마다 서로 다른 끝자리가 몇 종류였는지를 셉니다. "
    "1~45에는 끝자리 0이 4개(10·20·30·40), 1~5가 5개씩, 6~9가 4개씩 있어 기대 출현 수가 다릅니다."
)


# 목적: 끝자리별 출현 수·기대값과 회차별 끝자리 종류 수 분포를 계산한다.
# 이유: 끝자리마다 해당 번호 개수가 달라, 기대값 없이 출현 수만 보면 잘못 해석하기 쉽다.
# 방법: 끝자리별로 세고, 1~45 중 그 끝자리를 가진 번호 수 × 회차 수 × 6/45를 기대값으로 둔다.
def compute(draws) -> dict:
    total = len(draws)
    counts = [0] * 10
    distinct = [0] * 7
    for d in draws:
        digits = [n % 10 for n in d.numbers]
        for g in digits:
            counts[g] += 1
        distinct[len(set(digits))] += 1
    members = [sum(1 for n in range(1, 46) if n % 10 == g) for g in range(10)]
    return {
        "digits": [{"digit": g, "count": counts[g], "expected": round(total * members[g] * 6 / 45, 1)}
                   for g in range(10)],
        "distinct_distribution": [{"kinds": k, "rounds": distinct[k]} for k in range(1, 7)],
    }
