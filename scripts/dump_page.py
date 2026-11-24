"""把一个 PDF 页面的原始提取结果打出来，用来观察它"坏成什么样"。

用法：
    python scripts/dump_page.py data/xxx.pdf 4
"""
import sys

import pymupdf


def dump(path: str, page_no: int) -> None:
    doc = pymupdf.open(path)
    if page_no < 1 or page_no > doc.page_count:
        print(f"页码超出范围（1-{doc.page_count}）")
        return

    page = doc[page_no - 1]

    print("=" * 70)
    print(f"第 {page_no} 页　纯文本提取（get_text）")
    print("=" * 70)
    print(page.get_text("text"))
    print("=" * 70)

    print("\n表格检测与提取")
    print("=" * 70)
    found = page.find_tables()
    if not found.tables:
        print("本页未检测到表格")
    for idx, table in enumerate(found.tables, start=1):
        try:
            data = table.extract()
        except Exception as exc:  # noqa: BLE001
            print(f"\n--- 表格 {idx} 提取失败：{exc}")
            continue
        n_cols = max((len(r) for r in data), default=0)
        print(f"\n--- 表格 {idx}　{len(data)} 行 × {n_cols} 列 ---")
        for row in data:
            cells = ["" if c is None else str(c).replace("\n", "⏎") for c in row]
            print(" | ".join(cells))
    print("=" * 70)

    doc.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("用法：python scripts/dump_page.py <pdf> <页码>")
        raise SystemExit(1)
    dump(sys.argv[1], int(sys.argv[2]))
