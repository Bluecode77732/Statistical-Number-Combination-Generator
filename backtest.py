# 목적: 워크포워드 방식으로 과거 회차를 순서대로 예측해 보고, 무작위 기준선과 성능을 비교한다.
# 사용처: pipeline.py가 분석 다음 단계에서 한 번 부른다.
# 근거: 기존 백테스트는 6개 무작위 선택만 시험했다. 후보 10개 모델을 시간 순서대로 검증할 별도 단계가 필요하다.

from __future__ import annotations

import math
import random
import time
from typing import Callable, Optional

import numpy as np

from excel_loader import LottoDraw
from models import (
    PICK,
    LogisticModel,
    describe_model_error,
    build_features,
    random_candidates,
    select_candidates,
    training_rows,
)

START_ROUND = 101   # 1~100회는 학습 준비 구간
SEED = 20021207     # 백테스트를 다시 돌려도 같은 결과가 나오게 고정한다 (1회 추첨일)
Z95 = 1.96

# 1~45에서 10개를 무작위로 고를 때 실제 6개와의 일치 개수 분포 (초기하분포)
THEORY_PMF = [math.comb(6, m) * math.comb(39, PICK - m) / math.comb(45, PICK) for m in range(7)]
THEORY_MEAN = PICK * 6 / 45
THEORY_SD = math.sqrt(PICK * (6 / 45) * (39 / 45) * (45 - PICK) / 44)

MODEL_LABELS = {"logistic": "로지스틱 회귀", "random": "무작위 기준선"}


# 목적: 한 모델의 회차별 일치 개수를 요약한다.
# 이유: 평균만 보면 우연한 차이를 실력으로 오해하기 쉬워, 오차 범위와 판정을 함께 내야 한다.
# 방법: 평균과 95% 범위를 구하고, 무작위 이론 평균과의 차이를 표준오차로 나눈 z값으로 판정한다.
def _summarize(key: str, matches: list[int]) -> dict:
    n = len(matches)
    mean = sum(matches) / n
    se = THEORY_SD / math.sqrt(n)
    z = (mean - THEORY_MEAN) / se
    if abs(z) < Z95:
        verdict = "무작위 기준선과 의미 있는 차이 없음"
    elif z > 0:
        verdict = "무작위 이론값보다 높음 (미래 당첨을 보장하지 않음)"
    else:
        verdict = "무작위 이론값보다 낮음"
    return {
        "key": key, "label": MODEL_LABELS[key], "rounds": n,
        "mean": round(mean, 4),
        "ci_low": round(mean - Z95 * se, 4), "ci_high": round(mean + Z95 * se, 4),
        "z": round(z, 2), "verdict": verdict,
        "distribution": [matches.count(m) for m in range(7)],
    }


# 목적: START_ROUND부터 마지막 회차까지 워크포워드 백테스트를 수행한다.
# 이유: 각 회차를 그 이전 데이터로만 예측해야 실제 사용 상황과 같은 조건의 성능을 잴 수 있다.
#       후보 선택은 최종 후보와 같은 select_candidates(오차 안의 점수 차이는 동점)를 써야 화면의 판정이 그 방식의 성능이 된다.
# 방법: 회차 t마다 1~t−1회로 로지스틱 회귀를 갱신(직전 가중치에서 이어서 학습)하고 후보 10개를 만든다.
#       같은 회차에 무작위 기준선 후보도 만든다. 예측과 실제는 따로 모으고, 집계 때만 맞춰 본다.
#       마지막에 전체 데이터로 학습한 모델을 같은 회차들에 다시 적용해(표본 내 성능) 과적합 여부를 본다.
#       모델 단계의 오류는 종류와 상관없이 그 회차만 model_errors에 남기고 기준선은 계속한다(감사 A-01).
def run_backtest(
    draws: list[LottoDraw],
    start_round: int = START_ROUND,
    progress: Optional[Callable[[str], None]] = None,
    seed: int = SEED,
) -> dict:
    ordered = sorted(draws, key=lambda d: d.round_no)
    tests = [i for i, d in enumerate(ordered) if d.round_no >= start_round and i >= 2]
    if not tests:
        return {"ran": False, "message": f"{start_round}회차 이후 데이터가 없어 백테스트를 하지 못했습니다."}

    started = time.monotonic()
    X, hits = build_features(ordered)
    rng_np = np.random.default_rng(seed)
    rng_rand = random.Random(seed)

    predictions: list[dict] = []
    matches = {"logistic": [], "random": []}
    model_errors: list[str] = []
    weights_init = None
    say = progress or (lambda _m: None)

    for step, t in enumerate(tests):
        actual = set(ordered[t].numbers)
        rnd = random_candidates(rng_rand)
        predictions.append({"round": ordered[t].round_no, "model": "random",
                            "model_label": MODEL_LABELS["random"], "candidates": rnd})
        matches["random"].append(len(actual & set(rnd)))
        try:
            Xtr, ytr = training_rows(X, hits, t)
            model = LogisticModel().fit(Xtr, ytr, init=weights_init)
            weights_init = model.w
            lr = select_candidates(*model.logits_with_cov(X[t]), rng_np)["numbers"]
            predictions.append({"round": ordered[t].round_no, "model": "logistic",
                                "model_label": MODEL_LABELS["logistic"], "candidates": lr})
            matches["logistic"].append(len(actual & set(lr)))
        except Exception as exc:  # noqa: BLE001 - 한 회차의 모델 실패가 백테스트 전체를 멈추지 않게 한다(규칙 10)
            model_errors.append(f"{ordered[t].round_no}회차: {describe_model_error(exc)}")
        if step % 100 == 0:
            say(f"백테스트 중: {ordered[t].round_no}회차 ({step + 1}/{len(tests)})")

    actuals = [{"round": ordered[t].round_no, "numbers": ordered[t].numbers, "bonus": ordered[t].bonus}
               for t in tests]
    summaries = [_summarize("random", matches["random"])]
    if matches["logistic"]:
        summaries.insert(0, _summarize("logistic", matches["logistic"]))

    in_sample = None
    try:
        Xall, yall = training_rows(X, hits, len(ordered))
        full = LogisticModel().fit(Xall, yall)
        rng_is = np.random.default_rng(seed + 1)
        is_matches = [len(set(ordered[t].numbers) & set(select_candidates(*full.logits_with_cov(X[t]), rng_is)["numbers"]))
                      for t in tests]
        in_sample = round(sum(is_matches) / len(is_matches), 4)
    except Exception as exc:  # noqa: BLE001 - 진단용 값이라 실패해도 백테스트 결과는 낸다
        model_errors.append(f"전체 학습: {describe_model_error(exc)}")

    return {
        "ran": True,
        "start_round": ordered[tests[0]].round_no,
        "end_round": ordered[tests[-1]].round_no,
        "data_range": [ordered[0].round_no, ordered[-1].round_no],
        "rounds": len(tests),
        "seconds": round(time.monotonic() - started, 1),
        "theory": {"mean": round(THEORY_MEAN, 4), "sd": round(THEORY_SD, 4), "z95": Z95,
                   "expected_distribution": [round(p * len(tests), 1) for p in THEORY_PMF]},
        "summaries": summaries,
        "in_sample_mean": in_sample,
        "predictions": predictions,
        "actuals": actuals,
        "model_errors": model_errors,
    }
