"""PDF 体检：先搞清楚它坏在哪，再决定怎么解析。

这是 RAG 项目里最该先写的一个脚本——它不会解析出好东西，
只会告诉你这份文档有哪几类问题，以及值不值得修。

用法：
    python scripts/inspect_pdf.py data/xxx.pdf
"""
import sys
from collections import Counter
from pathlib import Path

import fitz  # PyMuPDF


def inspect(path: str) -> None:
    doc = fitz.open(path)
    n = doc.page_count

    print("=" * 62)
    print(f"文件   : {Path(path).name}")
    print(f"页数   : {n}")
    print(f"加密   : {doc.is_encrypted}")
    print("=" * 62)

    # ---------- 1. 文本量分布：找扫描页 ----------
    char_counts = [len(p.get_text("text").strip()) for p in doc]
    total = sum(char_counts)
    print("\n【1】文本量")
    print(f"  总字符数 : {total}")
    print(f"  平均每页 : {total / n:.0f}")
    print(f"  最少一页 : 第 {char_counts.index(min(char_counts)) + 1} 页（{min(char_counts)} 字符）")
    print(f"  最多一页 : 第 {char_counts.index(max(char_counts)) + 1} 页（{max(char_counts)} 字符）")

    empty = [i + 1 for i, c in enumerate(char_counts) if c < 50]
    if empty:
        head = empty[:10]
        more = " ..." if len(empty) > 10 else ""
        print(f"  ⚠ 疑似扫描页/纯图页：{head}{more}　共 {len(empty)} 页")

    # ---------- 2. 高频重复行：页眉页脚 ----------
    counter: Counter[str] = Counter()
    for page in doc:
        seen = set()
        for line in page.get_text("text").splitlines():
            s = line.strip()
            if 3 <= len(s) <= 40:
                seen.add(s)
        counter.update(seen)

    threshold = max(3, int(n * 0.4))
    repeated = [(s, c) for s, c in counter.most_common(20) if c >= threshold]

    print("\n【2】高频重复行（页眉 / 页脚嫌疑）")
    if repeated:
        for s, c in repeated:
            print(f"  {c:>4} 页 | {s!r}")
    else:
        print("  未发现明显重复行")

    # ---------- 3. 表格 ----------
    print("\n【3】表格检测")
    table_pages: list[tuple[int, int]] = []
    for i, page in enumerate(doc):
        try:
            found = page.find_tables()
            if found.tables:
                table_pages.append((i + 1, len(found.tables)))
        except Exception as exc:  # noqa: BLE001
            print(f"  第 {i + 1} 页检测失败：{exc}")

    if table_pages:
        print(f"  含表格的页：{table_pages[:15]}")
        print(f"  合计 {sum(c for _, c in table_pages)} 个表格，分布在 {len(table_pages)} 页")
    else:
        print("  未检测到表格（可能是扫描件，或表格被画成了图片）")

    # ---------- 4. 多栏嫌疑 ----------
    print("\n【4】多栏排版嫌疑")
    multi = []
    for i, page in enumerate(doc):
        w = page.rect.width
        blocks = page.get_text("blocks")
        left = [b for b in blocks if b[2] < w * 0.55 and len(b[4].strip()) > 20]
        right = [b for b in blocks if b[0] > w * 0.55 and len(b[4].strip()) > 20]
        if left and right:
            multi.append(i + 1)

    if multi:
        print(f"  疑似多栏页：{multi[:15]}　共 {len(multi)} 页")
    else:
        print("  未发现明显多栏")

    # ---------- 5. 首屏样本 ----------
    print("\n【5】第一页文本样本（前 600 字）")
    print("-" * 62)
    print(doc[0].get_text("text")[:600])
    print("-" * 62)

    doc.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法：python scripts/inspect_pdf.py <pdf 路径>")
        raise SystemExit(1)
    inspect(sys.argv[1])
