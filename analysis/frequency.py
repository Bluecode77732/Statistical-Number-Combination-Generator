# 목적: 1~45 각 번호가 당첨번호에 든 횟수를 센다.
# 사용처: analysis.run_all이 부른다. 결과는 표시용이며 후보 선정에 직접 쓰지 않는다.
# 근거: 요구된 분석 항목 1번. 다른 항목과 독립적으로 바꿀 수 있게 따로 둔다.

from __future__ import annotations

KEY = "frequency"
TITLE = "번호별 출현 빈도"
METHOD = (
    "1~45 각 번호가 회차별 당첨번호 6개에 들어간 횟수를 셉니다. 보너스 번호는 따로 셉니다. "
    "기대값은 회차 수 × 6 / 45입니다. 이 결과만으로 후보를 고르지 않습니다."
)


# 목적: 번호별 출현 횟수와 기대값의 차이를 계산한다.
# 이유: 빈도는 참고 통계로 보여 주되, 우연 범위 안의 차이인지 판단할 기준(기대값)이 함께 있어야 한다.
# 방법: 당첨번호와 보너스를 따로 센 뒤, 기대값과 차이를 번호순으로 돌려준다.
def compute(draws) -> dict:
    main = [0] * 46
    bonus = [0] * 46
    for d in draws:
        for n in d.numbers:
            main[n] += 1
        if d.bonus:
            bonus[d.bonus] += 1
    expected = round(len(draws) * 6 / 45, 2)
    rows = [{"number": n, "count": main[n], "bonus_count": bonus[n], "diff": round(main[n] - expected, 2)}
            for n in range(1, 46)]
    return {"expected": expected, "rows": rows,
            "max": max(rows, key=lambda r: r["count"])["number"],
            "min": min(rows, key=lambda r: r["count"])["number"]}
