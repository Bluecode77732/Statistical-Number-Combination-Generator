# 목적: 다음 회차용 후보 숫자 10개 한 세트를 만든다.
# 사용처: pipeline.py가 마지막 단계에서 한 번(next_candidates), 번호 재산출 때마다(redraw_candidates) 부른다.
# 근거: 기존 generator.py(6개 무작위)를 대체한다. 후보는 백테스트한 것과 같은 모델·특징값으로 만들어야 한다.

from __future__ import annotations

import random

import numpy as np

from excel_loader import LottoDraw
from models import (
    FREQ_ROUNDS, RECENT_ROUNDS, LogisticModel, build_features, describe_model_error, mixed_candidates, random_candidates,
    top_candidates, training_rows,
)

MIN_ROUNDS = 30  # 이보다 적으면 학습할 근거가 너무 적어 무작위로 대체한다
MIX_MIN_ROUNDS = FREQ_ROUNDS  # 재산출 규칙은 최근 50회 출현 횟수를 쓰므로 이보다 적으면 무작위로 대체한다


# 목적: 결과에 직전 회차 번호와 후보가 겹친 번호를 붙인다.
# 이유: 화면이 "직전 번호가 들어 있어도 근거가 아니다"를 실제 겹침 개수와 함께 설명하게 하기 위해서다.
# 방법: 마지막 회차의 당첨번호 6개와 후보 10개의 교집합을 오름차순으로 담는다. 무작위 대체에도 붙인다.
def _with_previous(ordered: list[LottoDraw], result: dict) -> dict:
    if ordered:
        prev = ordered[-1]
        result["previous_round"] = prev.round_no
        result["previous_overlap"] = sorted(set(prev.numbers) & set(result["numbers"]))
    return result


# 목적: 이유를 밝힌 무작위 대체 후보 10개를 만든다.
# 이유: 모델을 쓸 수 없을 때(데이터 부족, 학습 실패, 예상하지 못한 오류) 후보 없이 끝나면 안 된다(핵심 규칙 10).
#       파이프라인이 도중에 멈췄을 때도 같은 모양으로 대체 후보를 내도록 따로 둔다(감사 A-01).
# 방법: 운영체제 난수로 1~45에서 10개를 뽑고, 대체 표시와 이유, 직전 회차 겹침을 붙인다.
def fallback_candidates(draws: list[LottoDraw], reason: str) -> dict:
    ordered = sorted(draws, key=lambda d: d.round_no)
    target = ordered[-1].round_no + 1 if ordered else 1
    return _with_previous(ordered, {
        "target_round": target, "numbers": random_candidates(random.SystemRandom()),
        "method": "random", "method_label": "무작위 대체", "fallback_reason": reason, "weights": []})


# 목적: 전체 데이터로 로지스틱 회귀를 학습하고 다음 회차용 점수와 출현 행렬을 돌려준다.
# 이유: 첫 산출(상위 10개)과 재산출(상위 5개)이 같은 학습·같은 점수를 써야 "모델 점수 상위"가 같은 뜻이 된다.
# 방법: 1~마지막 회차로 학습하고 다음 회차용 특징값(X[N])의 점수를 계산한다. 오류는 부른 쪽이 잡는다.
def _train(ordered: list[LottoDraw]) -> tuple[LogisticModel, np.ndarray, np.ndarray]:
    X, hits = build_features(ordered)
    Xtr, ytr = training_rows(X, hits, len(ordered))
    model = LogisticModel().fit(Xtr, ytr)
    return model, model.scores(X[len(ordered)]), hits


# 목적: 전체 데이터로 학습한 로지스틱 회귀의 점수 상위 10개로 다음 회차 후보를 고른다.
# 이유: 최종 후보는 항상 로지스틱 회귀로 낸다는 결정(설계 문서 9절)을 따른다. 2026-11-20 사용자 결정으로 오차 안의
#       점수 차이를 동점으로 보던 방식(2026-11-09)을 거두고 점수 상위 10개로 돌아갔다. 실패하면 이유와 함께 무작위로 대체한다.
#       직전 회차 번호가 많이 들어가도 막지 않되(사용자 결정), 화면이 그 개수를 밝히도록 겹침을 붙인다.
# 방법: _train의 점수로 top_candidates를 부른다. 점수가 정확히 같을 때만 쓰는 순서 가르기와 대체용 무작위는
#       운영체제 난수를 쓴다. ModelError가 아닌 오류(예: LinAlgError)도 잡아 무작위로 대체한다(핵심 규칙 10, 감사 A-01).
def next_candidates(draws: list[LottoDraw]) -> dict:
    ordered = sorted(draws, key=lambda d: d.round_no)
    target = ordered[-1].round_no + 1 if ordered else 1
    sys_rng = random.SystemRandom()

    if len(ordered) < MIN_ROUNDS:
        return fallback_candidates(
            ordered, f"데이터가 {len(ordered)}회차뿐이라 모델을 학습하지 않았습니다(최소 {MIN_ROUNDS}회차).")

    try:
        model, scores, _ = _train(ordered)
        numbers = top_candidates(scores, np.random.default_rng(sys_rng.getrandbits(64)))
    except Exception as exc:  # noqa: BLE001 - 모델을 쓸 수 없으면 어떤 오류든 무작위로 대체한다(규칙 10)
        return fallback_candidates(ordered, f"모델 학습에 실패했습니다: {describe_model_error(exc)}")

    return _with_previous(ordered, {
        "target_round": target,
        "numbers": numbers,
        "method": "logistic",
        "method_label": "로지스틱 회귀 점수 상위 10개",
        "fallback_reason": None,
        "weights": model.weights(),
        "scores": [{"number": k + 1, "score": round(float(s), 4)} for k, s in enumerate(scores)],
    })


# 목적: 번호 재산출 규칙(점수 상위 5 + 최근 5회 2 + 최근 50회 빈도 3)으로 다음 회차 후보 10개를 고른다.
# 이유: "번호 재산출" 버튼의 선택 방식이다(2026-11-20 사용자 결정). 묶음별로 무엇을 골랐는지와 그 기준이 된
#       회차 범위를 화면이 밝힐 수 있게 함께 돌려준다(핵심 규칙 7). 50회보다 적거나 모델이 실패하면 규칙 10대로 대체한다.
# 방법: _train의 점수와 전체 출현 행렬로 mixed_candidates를 부른다. 무작위 자리는 운영체제 난수라 누를 때마다 바뀐다.
#       최근 5회·50회의 회차 범위는 마지막 회차에서 거꾸로 센 값이다.
def redraw_candidates(draws: list[LottoDraw]) -> dict:
    ordered = sorted(draws, key=lambda d: d.round_no)
    target = ordered[-1].round_no + 1 if ordered else 1
    sys_rng = random.SystemRandom()

    if len(ordered) < MIX_MIN_ROUNDS:
        return fallback_candidates(
            ordered, f"데이터가 {len(ordered)}회차뿐이라 재산출 규칙(최근 {FREQ_ROUNDS}회 출현 횟수 사용)을 쓸 수 없습니다"
                     f"(최소 {MIX_MIN_ROUNDS}회차).")

    try:
        model, scores, hits = _train(ordered)
        mixed = mixed_candidates(scores, hits, np.random.default_rng(sys_rng.getrandbits(64)))
    except Exception as exc:  # noqa: BLE001 - 모델을 쓸 수 없으면 어떤 오류든 무작위로 대체한다(규칙 10)
        return fallback_candidates(ordered, f"모델 학습에 실패했습니다: {describe_model_error(exc)}")

    return _with_previous(ordered, {
        "target_round": target,
        "numbers": mixed["numbers"],
        "method": "mixed",
        "method_label": "재산출 규칙(점수 상위 5 · 최근 5회 2 · 최근 50회 빈도 3)",
        "fallback_reason": None,
        "groups": mixed["groups"],
        "recent_rounds": [ordered[-RECENT_ROUNDS].round_no, ordered[-1].round_no],
        "freq_rounds": [ordered[-FREQ_ROUNDS].round_no, ordered[-1].round_no],
        "weights": model.weights(),
        "scores": [{"number": k + 1, "score": round(float(s), 4)} for k, s in enumerate(scores)],
    })
