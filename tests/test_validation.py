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


def xlsx(df, header=True, startrow=0):
    buf = io.BytesIO()
    df.to_excel(buf, index=False, header=header, startrow=startrow)
    return buf.getvalue()


class LoaderTest(unittest.TestCase):
    def test_headered_file_skips_invalid_rows_with_row_numbers(self):
        r = load_excel(xlsx(pd.DataFrame(ROWS, columns=HEADER)), "a.xlsx")
        self.assertEqual([d.round_no for d in r.draws], [1, 2, 6])
        self.assertEqual([s["row"] for s in r.skipped_rows], [4, 5, 6])
        self.assertIn("보너스", r.skipped_rows[2]["reason"])

    def test_headerless_file_still_loads(self):  # 기존 기능 회귀
        r = load_excel(xlsx(pd.DataFrame(ROWS), header=False, startrow=1), "b.xlsx")
        self.assertEqual([d.round_no for d in r.draws], [1, 2, 6])
        self.assertEqual([s["row"] for s in r.skipped_rows], [4, 5, 6])

    def test_wrong_columns_rejected_in_korean(self):
        with self.assertRaises(ExcelValidationError) as ctx:
            load_excel(xlsx(pd.DataFrame({"A": [1, 2], "B": [3, 4]}), header=False), "c.xlsx")
        self.assertIn("회차", str(ctx.exception))

    def test_non_excel_rejected(self):
        with self.assertRaises(ExcelValidationError):
            load_excel(b"abc", "d.txt")

    def test_date_column_is_read(self):
        df = pd.DataFrame([[1, "2002-12-07", 10, 23, 29, 33, 37, 40, 16]],
                          columns=["회차", "추첨일", *HEADER[1:]])
        r = load_excel(xlsx(df), "e.xlsx")
        self.assertEqual(r.draws[0].draw_date, "2002-12-07")


class SequenceTest(unittest.TestCase):
    def test_missing_and_duplicate_rounds(self):
        draws = [LottoDraw(n, [1, 2, 3, 4, 5, 6]) for n in (1, 2, 4, 4, 5)]
        self.assertEqual(check_sequence(draws), {"duplicates": [4], "missing": [3]})

    def test_clean_sequence(self):
        draws = [LottoDraw(n, [1, 2, 3, 4, 5, 6]) for n in range(1, 6)]
        self.assertEqual(check_sequence(draws), {"duplicates": [], "missing": []})


if __name__ == "__main__":
    unittest.main()
