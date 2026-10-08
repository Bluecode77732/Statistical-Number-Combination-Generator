# 목적: 배포용 실행 파일 폴더(dist\LottoAnalyzer)와 zip을 만든다.
# 사용처: 프로젝트 폴더에서 `.\build.ps1` 로 직접 실행한다.
# 근거: PyInstaller 옵션이 길어 매번 손으로 치면 static 폴더 누락 같은 실수가 난다.

# PyInstaller는 진행 로그를 stderr로 내보낸다. 전역 Stop을 걸면 그 로그가 오류로 처리되므로,
# 외부 프로그램은 종료 코드로, cmdlet은 개별 -ErrorAction Stop으로 실패를 잡는다.
Set-Location $PSScriptRoot

$python = ".\.venv\Scripts\python.exe"
& $python -m pip install --quiet -r requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw "빌드 도구 설치 실패" }

& $python -m PyInstaller --noconfirm --clean --console `
    --name LottoAnalyzer `
    --add-data "static;static" `
    --collect-submodules uvicorn `
    launcher.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 빌드 실패" }

Copy-Item "packaging\사용법.txt" "dist\LottoAnalyzer\사용법.txt" -Force -ErrorAction Stop

# Compress-Archive는 백신이 방금 만든 파일을 검사하는 동안 "접근 거부"로 실패하고,
# .NET ZipFile은 경로 구분자를 역슬래시로 써서 일부 압축 프로그램에서 풀리지 않는다. 그래서 Python으로 묶는다.
$zip = "dist\LottoAnalyzer.zip"
if (Test-Path $zip) { Remove-Item $zip -ErrorAction Stop }
& $python -c "import shutil; shutil.make_archive('dist/LottoAnalyzer', 'zip', 'dist', 'LottoAnalyzer')"
if ($LASTEXITCODE -ne 0) { throw "zip 생성 실패" }
Write-Output "완료: $zip"
