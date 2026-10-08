"""API 요청/응답에 사용하는 Pydantic 모델."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class SkippedRow(BaseModel):
    row: int
    reason: str


class SumStatsModel(BaseModel):
    min: int
    max: int
    avg: float
    median: float


class ConsecutivePairRatioModel(BaseModel):
    with_consecutive: int
    without_consecutive: int
    percentage: float


class AnalysisResultModel(BaseModel):
    total_rounds: int
    first_round: int
    last_round: int
    sum_stats: SumStatsModel
    odd_count_distribution: dict[str, int]
    high_count_distribution: dict[str, int]
    consecutive_pair_ratio: ConsecutivePairRatioModel


class BacktestResultModel(BaseModel):
    simulated_rounds: int
    match_distribution: dict[str, int]
    average_matches: float
    theoretical_average_matches: float
    note: str


class ColumnsUsedModel(BaseModel):
    round: str
    numbers: list[str]
    bonus: Optional[str] = None


class AnalyzeResponse(BaseModel):
    file_name: str
    columns_used: ColumnsUsedModel
    skipped_rows: list[SkippedRow]
    analysis: AnalysisResultModel
    backtest: BacktestResultModel


class GenerateResponse(BaseModel):
    numbers: list[int]


class ErrorResponse(BaseModel):
    detail: str
