# 목적: 다음 회차용 후보 숫자 10개 한 세트를 만든다.
# 사용처: pipeline.py가 마지막 단계에서 한 번 부른다.
# 근거: 기존 generator.py(6개 무작위)를 대체한다. 후보는 백테스트한 것과 같은 모델·특징값으로 만들어야 한다.

from __future__ import annotations

import random

import numpy as np

from excel_loader import LottoDraw
from models import (
    TIE_Z, LogisticModel, ModelError, build_features, random_candidates, select_candidates, training_rows,
)

MIN_ROUNDS = 30  # 이보다 적으면 학습할 근거가 너무 적어 무작위로 대체한다


# 목적: 전체 데이터로 학습한 로지스틱 회귀로 다음 회차 후보 10개를 고른다.
# 이유: 최종 후보는 항상 로지스틱 회귀로 낸다는 결정(설계 문서 9절)을 따른다. 실패하면 이유와 함께 무작위로 대체한다.
#       점수 차이가 오차 안이면 동점으로 보고(2026-11-09 결정), 화면이 그 사실과 직전 회차와의 겹침을 설명할 수 있게
#       확정 번호, 동점 묶음 크기, 직전 회차 번호와 겹친 개수를 함께 돌려준다.
# 방법: 1~마지막 회차로 학습하고, 다음 회차용 특징값(X[N])의 점수와 공분산으로 select_candidates를 부른다.
#       동점 처리와 대체용 무작위는 운영체제 난수를 써서 실행마다 고정되지 않게 한다.
def next_candidates(draws: list[LottoDraw]) -> dict:
    ordered = sorted(draws, key=lambda d: d.round_no)
    target = ordered[-1].round_no + 1 if ordered else 1
    sys_rng = random.SystemRandom()

    # 목적: 결과에 직전 회차 번호와 후보가 겹친 번호를 붙인다.
    # 이유: 화면이 "직전 번호가 들어 있어도 근거가 아니다"를 실제 겹침 개수와 함께 설명하게 하기 위해서다.
    # 방법: 마지막 회차의 당첨번호 6개와 후보 10개의 교집합을 오름차순으로 담는다. 무작위 대체에도 붙인다.
    def with_previous(result: dict) -> dict:
        if ordered:
            prev = ordered[-1]
            result["previous_round"] = prev.round_no
            result["previous_overlap"] = sorted(set(prev.numbers) & set(result["numbers"]))
        return result

    def fallback(reason: str) -> dict:
        return with_previous({"target_round": target, "numbers": random_candidates(sys_rng),
                              "method": "random", "method_label": "무작위 대체", "fallback_reason": reason,
                              "weights": []})

    if len(ordered) < MIN_ROUNDS:
        return fallback(f"데이터가 {len(ordered)}회차뿐이라 모델을 학습하지 않았습니다(최소 {MIN_ROUNDS}회차).")

    try:
        X, hits = build_features(ordered)
        Xtr, ytr = training_rows(X, hits, len(ordered))
        model = LogisticModel().fit(Xtr, ytr)
        scores = model.scores(X[len(ordered)])
        chosen = select_candidates(*model.logits_with_cov(X[len(ordered)]),
                                   np.random.default_rng(sys_rng.getrandbits(64)))
    except ModelError as exc:
        return fallback(f"모델 학습에 실패했습니다: {exc}")

    return with_previous({
        "target_round": target,
        "numbers": chosen["numbers"],
        "method": "logistic",
        "method_label": "로지스틱 회귀",
        "fallback_reason": None,
        "firm": chosen["firm"],
        "tie_pool": chosen["tie_pool"],
        "tie_z": TIE_Z,
        "weights": model.weights(),
        "scores": [{"number": k + 1, "score": round(float(s), 4)} for k, s in enumerate(scores)],
    })
