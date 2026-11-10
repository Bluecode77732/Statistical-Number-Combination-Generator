import io
import unittest

import pandas as pd

from excel_loader import ExcelValidationError, LottoDraw, check_sequence, load_excel

HEADER = ["회차", "번호1", "번호2", "번호3", "번호4", "번호5", "번호6", "보너스번호"]
ROWS = [
    [1, 10, 23, 29, 33, 37, 40, 16],
    [2, 9, 13, 21, 25, 32, 42, 2],
    [3, 5, 5, 19, 21, 27, 31, 30],   # 번호 중복
    [4, 14, 27, 30, 31, 40, 46, 2],  # 범위 밖
    [5, 8, 16, 26, 29, 31, 36, 26],  # 보너스가 당첨번호와 중복 (사용자 파일 1040회와 같은 유형)
    [6, 1, 2, 3, 4, 5, 6, 7],
]


def xlsx(df, header=True):
    buf = io.BytesIO()
    df.to_excel(buf, index=False, header=header)
    return buf.getvalue()


class LoaderTest(unittest.TestCase):
    def test_headered_file_skips_invalid_rows_with_row_numbers(self):
        r = load_excel(xlsx(pd.DataFrame(ROWS, columns=HEADER)))
        self.assertEqual([d.round_no for d in r.draws], [1, 2, 6])
        self.assertEqual([s["row"] for s in r.skipped_rows], [4, 5, 6])
        self.assertIn("보너스", r.skipped_rows[2]["reason"])

    # 목적: 제목 행이 없는 파일은 읽지 않고, 빠진 컬럼 이름을 한글로 알리는지 확인한다.
    # 이유: 전용 엑셀만 읽으므로 제목 행 없는 읽기를 지웠다(결정 D-5). 숫자만 든 파일을 다른 열로 잘못 읽으면 안 된다.
    # 방법: 제목 행 없이 숫자만 쓴 파일을 읽어 ExcelValidationError와 '회차'가 든 메시지를 기대한다.
    def test_headerless_file_rejected_in_korean(self):
        with self.assertRaises(ExcelValidationError) as ctx:
            load_excel(xlsx(pd.DataFrame(ROWS), header=False))
        self.assertIn("회차", str(ctx.exception))

    # 목적: 예전 별칭(round, num1 등)으로 된 제목 행은 받지 않는지 확인한다.
    # 이유: 컬럼 별칭은 전용 엑셀에 쓰이지 않아 지웠다(결정 D-5).
    # 방법: 영어 별칭 제목 행으로 읽어 오류 메시지에 빠진 한글 컬럼 이름이 나오는지 본다.
    def test_alias_header_rejected(self):
        cols = ["round", "num1", "num2", "num3", "num4", "num5", "num6", "bonus"]
        with self.assertRaises(ExcelValidationError) as ctx:
            load_excel(xlsx(pd.DataFrame(ROWS, columns=cols)))
        self.assertIn("번호1", str(ctx.exception))

    def test_non_excel_rejected(self):
        with self.assertRaises(ExcelValidationError):
            load_excel(b"abc")

    def test_date_column_is_read(self):
        df = pd.DataFrame([[1, "2002-12-07", 10, 23, 29, 33, 37, 40, 16]],
                          columns=["회차", "추첨일", *HEADER[1:]])
        r = load_excel(xlsx(df))
        self.assertEqual(r.draws[0].draw_date, "2002-12-07")

    # 목적: 소수 번호, 1 미만 회차, 범위 밖 보너스, 달력에 없는 날짜가 있는 행을 모두 건너뛰는지 확인한다.
    # 이유: 예전에는 1.9가 1로 잘려 읽히고 나머지도 그대로 통과했다(감사 A-10).
    # 방법: 정상 행 하나와 불량 행 네 개를 섞어 읽고, 정상 행만 남고 행 번호와 사유가 맞는지 본다.
    def test_bad_cells_are_skipped_with_reasons(self):
        cols = ["회차", "추첨일", *HEADER[1:]]
        rows = [
            [1, "2002-12-07", 10, 23, 29, 33, 37, 40, 16],   # 정상
            [2, "2002-12-14", 9.5, 13, 21, 25, 32, 42, 2],   # 번호가 소수
            [0, "2002-12-21", 5, 8, 19, 21, 27, 31, 30],     # 회차 0
            [4, "2002-12-28", 14, 27, 30, 31, 40, 44, 99],   # 보너스 범위 밖
            [5, "2026-13-99", 8, 16, 26, 29, 31, 36, 7],     # 달력에 없는 날짜
        ]
        r = load_excel(xlsx(pd.DataFrame(rows, columns=cols)))
        self.assertEqual([d.round_no for d in r.draws], [1])
        self.assertEqual([s["row"] for s in r.skipped_rows], [3, 4, 5, 6])
        reasons = " / ".join(s["reason"] for s in r.skipped_rows)
        for word in ("정수", "회차", "보너스", "날짜"):
            self.assertIn(word, reasons)

    # 목적: 보너스나 추첨일 칸이 빈 옛 형식 행은 그대로 읽히는지 확인한다.
    # 이유: 검증을 강화하면서 보너스·날짜가 없던 예전 파일까지 막으면 안 된다.
    # 방법: 두 칸이 빈 행을 읽어 보너스와 날짜가 None이고 행이 남는지 본다.
    def test_blank_bonus_and_date_are_still_allowed(self):
        cols = ["회차", "추첨일", *HEADER[1:]]
        rows = [[1, None, 10, 23, 29, 33, 37, 40, None]]
        r = load_excel(xlsx(pd.DataFrame(rows, columns=cols)))
        self.assertEqual(len(r.draws), 1)
        self.assertIsNone(r.draws[0].bonus)
        self.assertIsNone(r.draws[0].draw_date)
        self.assertEqual(r.skipped_rows, [])

    # 목적: 엑셀이 정수를 5.0처럼 실수로 돌려줘도 정수로 읽는지 확인한다.
    # 이유: 정수만 받도록 고치다가 빈 칸이 섞인 열의 정상 값까지 버리면 안 된다.
    # 방법: 번호와 회차를 실수로 넣은 행을 읽어 정수 값이 그대로 나오는지 본다.
    def test_integral_floats_are_accepted(self):
        rows = [[1.0, 10.0, 23.0, 29.0, 33.0, 37.0, 40.0, 16.0]]
        r = load_excel(xlsx(pd.DataFrame(rows, columns=HEADER)))
        self.assertEqual((r.draws[0].round_no, r.draws[0].numbers, r.draws[0].bonus), (1, [10, 23, 29, 33, 37, 40], 16))


class SequenceTest(unittest.TestCase):
    def test_missing_and_duplicate_rounds(self):
        draws = [LottoDraw(n, [1, 2, 3, 4, 5, 6]) for n in (1, 2, 4, 4, 5)]
        self.assertEqual(check_sequence(draws), {"duplicates": [4], "missing": [3]})

    def test_clean_sequence(self):
        draws = [LottoDraw(n, [1, 2, 3, 4, 5, 6]) for n in range(1, 6)]
        self.assertEqual(check_sequence(draws), {"duplicates": [], "missing": []})


if __name__ == "__main__":
    unittest.main()
