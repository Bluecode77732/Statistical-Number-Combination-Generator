# 목적: 더블클릭 한 번으로 서버를 켜고 브라우저에 화면을 띄우는 실행 파일용 진입점.
# 사용처: build.ps1이 PyInstaller로 이 파일을 묶어 LottoAnalyzer.exe를 만든다. 개발 중에는 main.py를 그대로 쓴다.
# 근거: 받는 사람은 터미널 명령을 치지 않으므로, 포트 선택과 브라우저 열기를 main.py와 분리해 여기서 맡는다.

from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser

import uvicorn

from main import app

try:
    import winreg
except ImportError:  # Windows가 아닌 환경에서는 레지스트리 조회를 건너뛴다
    winreg = None

HOST = "127.0.0.1"
PREFERRED_PORT = 8000

# (실행 파일 이름, 방문 기록을 남기지 않는 창으로 여는 옵션) — 앞에서부터 차례로 시도한다.
PRIVATE_BROWSERS = (("msedge.exe", "--inprivate"), ("chrome.exe", "--incognito"))


# 목적: 설치된 브라우저 실행 파일의 경로를 찾는다.
# 이유: Edge와 Chrome은 보통 PATH에 없어서 이름만으로는 실행할 수 없다.
# 방법: Windows가 프로그램 경로를 적어 두는 레지스트리(App Paths)를 먼저 보고, 없으면 PATH에서 찾는다.
def find_browser(exe_name: str) -> str | None:
    if winreg is not None:
        key_path = rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe_name}"
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(root, key_path) as key:
                    path = winreg.QueryValue(key, None)
            except OSError:
                continue
            if path:
                return path
    return shutil.which(exe_name)


# 목적: 방문 기록과 캐시를 남기지 않는 창으로 화면을 연다.
# 이유: 일반 창으로 열면 브라우저 방문 기록에 주소와 제목이 남는다.
# 방법: Edge InPrivate, Chrome 시크릿 순으로 시도하고, 둘 다 없으면 False를 돌려 호출한 쪽이 기본 브라우저로 열게 한다.
def open_private_window(url: str) -> bool:
    for exe_name, flag in PRIVATE_BROWSERS:
        path = find_browser(exe_name)
        if not path:
            continue
        try:
            subprocess.Popen([path, flag, url])
        except OSError:
            continue
        return True
    return False


# 목적: 서버가 쓸 포트를 정한다.
# 이유: 8000번을 다른 프로그램이 쓰고 있으면 실행 자체가 실패한다.
# 방법: 8000번에 먼저 묶어 보고, 안 되면 운영체제가 주는 빈 포트를 받는다.
def pick_port() -> int:
    for port in (PREFERRED_PORT, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((HOST, port))
            except OSError:
                continue
            return sock.getsockname()[1]
    raise RuntimeError("사용할 수 있는 포트를 찾지 못했습니다.")


# 목적: 서버가 요청을 받을 준비가 되면 브라우저로 화면을 연다.
# 이유: 서버가 뜨기 전에 열면 브라우저에 연결 오류 화면이 먼저 보인다.
# 방법: 포트에 접속이 될 때까지 짧게 반복 확인한 뒤, 기록이 남지 않는 창을 먼저 시도하고 안 되면 기본 브라우저로 연다.
def open_browser_when_ready(port: int) -> None:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((HOST, port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.2)
    else:
        return
    url = f"http://{HOST}:{port}"
    if not open_private_window(url):
        webbrowser.open(url)


# 목적: 프로그램을 시작하고, 창을 닫을 때까지 서버를 유지한다.
# 이유: 실행 파일의 유일한 시작점이다.
# 방법: 포트를 고르고 안내를 출력한 뒤, 브라우저 열기는 별도 스레드에 맡기고 서버를 현재 스레드에서 돌린다.
def main() -> None:
    if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # 한글을 못 쓰는 콘솔에서도 죽지 않게 한다

    port = pick_port()
    print("로또 번호 분석 프로그램")
    print(f"  주소: http://{HOST}:{port}")
    print("  방문 기록이 남지 않는 창(InPrivate/시크릿)으로 자동으로 열립니다.")
    print("  열리지 않으면 위 주소를 브라우저에 직접 입력하세요.")
    print("  종료하려면 이 창을 닫으세요.")
    print()

    if "--no-browser" not in sys.argv:
        threading.Thread(target=open_browser_when_ready, args=(port,), daemon=True).start()

    uvicorn.run(app, host=HOST, port=port, log_level="warning")


if __name__ == "__main__":
    main()
