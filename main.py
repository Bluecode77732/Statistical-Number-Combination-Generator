"""
로또 번호 분석 프로그램 - FastAPI 진입점 (Local-only web app)

데이터 흐름:
    Excel 파일 업로드 -> 검증 -> 메모리에서 분석/백테스트 -> 결과 표시
    (사용자가 버튼을 누르면) -> 독립적인 랜덤 번호 생성기 -> 6개 번호 출력

분석 결과와 번호 생성기는 완전히 분리되어 있다.
/api/generate 는 /api/analyze 의 결과를 전혀 참조하지 않는다.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import analyzer
import generator
from excel_loader import ExcelValidationError, load_excel
from schemas import AnalyzeResponse, GenerateResponse

# 실행 파일(PyInstaller)로 묶이면 static 폴더가 sys._MEIPASS 아래에 풀린다.
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="로또 번호 분석 프로그램", description="로컬 전용 로또 데이터 분석 및 번호 생성 도구")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# 목적: 브라우저가 화면 파일과 응답을 디스크 캐시에 남기지 않게 한다.
# 이유: 같은 PC에서 읽어 오므로 캐시의 이득이 없고, 남기면 사용 흔적이 되며 새 버전으로 바꿨을 때 예전 화면이 보인다.
# 방법: 모든 응답에 Cache-Control: no-store 헤더를 붙인다.
@app.middleware("http")
async def no_store(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze_excel(file: UploadFile = File(...)) -> AnalyzeResponse:
    """사용자가 지정한 Excel 파일을 읽어 검증하고, 회차 단위 통계와
    백테스트 결과만 계산해 반환한다. 번호 생성기는 호출하지 않는다."""
    file_bytes = await file.read()

    try:
        result = load_excel(file_bytes, file.filename or "uploaded.xlsx")
    except ExcelValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    analysis = analyzer.analyze(result.draws)
    backtest = analyzer.backtest(result.draws)

    return AnalyzeResponse(
        file_name=result.source_filename,
        columns_used=result.columns_used,
        skipped_rows=result.skipped_rows,
        analysis=analysis,
        backtest=backtest,
    )


@app.post("/api/generate", response_model=GenerateResponse)
def generate() -> GenerateResponse:
    """1~45 중 중복 없이 6개를 무작위로 뽑아 오름차순으로 반환한다.
    분석 결과나 과거 데이터에는 전혀 접근하지 않는 독립된 호출이다."""
    numbers = generator.generate_numbers()
    return GenerateResponse(numbers=numbers)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)
