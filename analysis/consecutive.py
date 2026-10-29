# 목적: 회차별 연속번호(예: 12·13) 쌍이 몇 개 있었는지 집계한다.
# 사용처: analysis.run_all이 부른다.
# 근거: 요구된 분석 항목 4번. 다른 항목과 독립적으로 바꿀 수 있게 따로 둔다.

from __future__ import annotations

KEY = "consecutive"
TITLE = "연속번호 패턴"
METHOD = (
    "정렬한 당첨번호에서 차이가 1인 이웃 쌍의 수(0~5)를 회차마다 세어 집계합니다. "
    "12·13·14는 연속 쌍 2개로 셉니다."
)


# 목적: 연속 쌍 개수별 회차 수와 연속번호가 하나라도 있는 회차 비율을 계산한다.
# 이유: "연속번호가 자주 나온다"는 인상을 실제 수치로 확인할 수 있게 한다.
# 방법: 정렬된 6개의 이웃 차이가 1인 곳을 세어 분포로 모은다.
def compute(draws) -> dict:
    dist = [0] * 6
    for d in draws:
        s = sorted(d.numbers)
        dist[sum(1 for a, b in zip(s, s[1:]) if b - a == 1)] += 1
    total = len(draws)
    with_any = total - dist[0]
    return {"distribution": [{"pairs": k, "rounds": dist[k]} for k in range(6)],
            "with_consecutive": with_any,
            "ratio": round(with_any / total * 100, 1) if total else 0.0}
