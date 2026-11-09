# 목적: FastAPI 앱에 화면과 API 주소만 있고, 외부 자원을 부르는 기본 문서 페이지가 없는지 확인한다.
# 사용처: python -m unittest discover -s tests -t . 로 다른 테스트와 함께 돈다.
# 근거: 핵심 규칙 2(외부 통신은 공식 조회뿐). /docs, /redoc이 CDN을 불렀다(감사 A-08).

import unittest

import main


class RoutesTest(unittest.TestCase):
    # 목적: 기본 문서 페이지와 OpenAPI 주소가 등록되지 않았는지 확인한다.
    # 이유: 누가 그 주소를 열면 cdn.jsdelivr.net으로 나가는 통신이 생겼다(감사 A-08).
    # 방법: 앱 설정값과 등록된 경로 목록을 본다(httpx가 없어 요청 대신 경로를 검사한다).
    def test_docs_pages_are_off(self):
        self.assertIsNone(main.app.docs_url)
        self.assertIsNone(main.app.redoc_url)
        self.assertIsNone(main.app.openapi_url)
        paths = {getattr(r, "path", "") for r in main.app.routes}
        for p in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
            self.assertNotIn(p, paths)

    # 목적: 화면과 API 주소는 그대로 있는지 확인한다.
    # 이유: 문서 페이지를 끄면서 쓰는 주소까지 빠지면 안 된다.
    # 방법: 등록된 경로 목록에 화면, 실행, 상태, 결과, 재산출, 정적 파일 주소가 있는지 본다.
    def test_app_routes_remain(self):
        paths = {getattr(r, "path", "") for r in main.app.routes}
        for p in ("/", "/api/run", "/api/status", "/api/result", "/api/redraw", "/static"):
            self.assertIn(p, paths)


if __name__ == "__main__":
    unittest.main()
