"""
로또 번호 분석 프로그램 - FastAPI 진입점 (Local-only web app)

데이터 흐름 (설계 문서 docs/DESIGN.md 4절):
    전용 엑셀 확인 -> 공식 데이터로 빠진 회차 업데이트(백업 후) -> 검증
    -> 통계 분석 9개 항목 -> 워크포워드 백테스트 -> 후보 숫자 10개 한 세트

화면을 열면 /api/run 으로 위 절차를 백그라운드에서 시작하고,
/api/status 로 단계별 진행을, /api/result 로 결과를 가져간다.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from pipeline import Pipeline, RedrawUnavailable

# 실행 파일(PyInstaller)로 묶이면 static 폴더가 sys._MEIPASS 아래에 풀린다.
BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
STATIC_DIR = BASE_DIR / "static"

# /docs, /redoc 페이지는 외부 CDN에서 스크립트를 불러오고 화면이 쓰지도 않으므로 끈다(핵심 규칙 2, 감사 A-08).
app = FastAPI(title="로또 번호 분석 프로그램", description="로컬 전용 로또 데이터 분석 및 후보 숫자 도구",
              docs_url=None, redoc_url=None, openapi_url=None)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

pipeline = Pipeline()


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


# 목적: 시작 절차를 백그라운드에서 시작한다.
# 이유: 첫 실행의 공식 데이터 수집이 몇 분 걸려, 요청 하나로 기다리게 할 수 없다.
# 방법: 이미 돌고 있으면 새로 시작하지 않고 현재 상태만 돌려준다.
@app.post("/api/run")
def run() -> dict:
    started = pipeline.start()
    return {"started": started, **pipeline.status()}


@app.get("/api/status")
def status() -> dict:
    return pipeline.status()


# 목적: 끝난 절차의 결과를 돌려준다.
# 이유: 진행 중에는 결과가 일부만 차 있어, 화면이 반쯤 찬 결과를 완성본으로 오해하지 않게 한다.
# 방법: 실행 중이면 409, 한 번도 실행하지 않았으면 404를 돌려준다. 실패여도 남은 결과는 그대로 준다.
@app.get("/api/result")
def result() -> dict:
    if pipeline.state == "running":
        raise HTTPException(status_code=409, detail="아직 실행 중입니다.")
    if pipeline.result is None:
        raise HTTPException(status_code=404, detail="아직 실행한 적이 없습니다.")
    return {"status": pipeline.status(), "result": pipeline.result}


# 목적: 마지막 실행의 데이터로 후보 10개만 새로 고른다.
# 이유: 전체 절차를 다시 돌리지 않고 새 후보 한 세트를 보게 하는 "번호 재산출" 버튼용이다.
# 방법: Pipeline.redraw에 넘기고, 지금 할 수 없으면(실행 중, 실행 전) 409와 다음에 할 일을 돌려준다.
@app.post("/api/redraw")
def redraw() -> dict:
    try:
        cand = pipeline.redraw()
    except RedrawUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": pipeline.status(), "candidates": cand}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, reload=False)
