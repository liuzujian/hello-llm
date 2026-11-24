"""对比两种表格单元格取文本的方式，找出标点错位的修法。

    A. table.extract()                     —— 当前用法，标点会跑位
    B. page.get_text(clip=cell, sort=True) —— 按坐标重新排序
"""
import sys

import pymupdf


def main(path: str, page_no: int) -> None:
    doc = pymupdf.open(path)
    page = doc[page_no - 1]
    tables = page.find_tables().tables
    if not tables:
        print("本页无表格")
        return

    t = tables[0]

    print("=" * 70)
    print("A. table.extract()")
    print("=" * 70)
    for row in t.extract():
        print(" | ".join("" if c is None else str(c).replace("\n", "⏎") for c in row))

    print()
    print("=" * 70)
    print("B. get_text(clip=cell, sort=True)")
    print("=" * 70)
    for row in t.rows:
        cells = []
        for rect in row.cells:
            if rect is None:
                cells.append("")
            else:
                cells.append(page.get_text("text", clip=rect, sort=True).strip().replace("\n", "⏎"))
        print(" | ".join(cells))

    doc.close()


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]))
