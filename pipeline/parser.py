"""PDF → 结构化文本：正文与表格彻底分开，不重复、不污染。

三个关键决策，每个都来自实测踩坑：

1. 表格必须走单独通道
   只用 get_text() 的话，表格会变成"一个格子一行"，行列关系全丢。

2. 单元格文本要用 clip + sort
   table.extract() 直接拼文本片段，中文标点（、，。）有独立坐标，
   会被拼到错误位置，出现"集合 、、"这种结果。

3. 正文必须排除表格区域
   否则同一份表格内容会存两次：塌的一份在 text 里，好的一份在
   tables 里。检索时会重复命中，白白浪费上下文窗口。

用法：
    python -m pipeline.parser data/xxx.pdf data/xxx.jsonl
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

import pymupdf

CJK = r"\u4e00-\u9fff"

PAGE_NUM_RE = re.compile(
    r"^第\s*\d+\s*页(\s*共\s*\d+\s*页)?$"
    r"|^\d+\s*/\s*\d+$"
    r"|^[-—\s]*\d+[-—\s]*$"
)

CJK_PUNCT = "，。、；：？！（）【】「」『』《》“”‘’"


def clean_line(s: str) -> str:
    """清理单行内的错位空格。不做换行处理。"""
    if not s:
        return ""
    s = re.sub(rf"(?<=[{CJK}])[ \t]+(?=[{CJK}])", "", s)
    s = re.sub(rf"[ \t]+([{CJK_PUNCT}])", r"\1", s)
    s = re.sub(rf"([{CJK_PUNCT}])[ \t]+", r"\1", s)
    s = re.sub(r"[ \t]{2,}", " ", s)
    return s.strip()


def clean_text(s: str, flatten: bool = False) -> str:
    """清理文本。

    flatten=True 用于表格单元格：换行没有意义，要压成一行。
    flatten=False 用于正文：必须保留换行，否则标题会和正文粘成一句，
    后续切分就再也找不回结构了。
    """
    if not s:
        return ""
    if flatten:
        return clean_line(s.replace("\n", " "))
    return "\n".join(filter(None, (clean_line(line) for line in s.splitlines())))


def detect_noise_lines(pages: list[str], min_pages: int = 3, ratio: float = 0.4) -> set[str]:
    """找出在大量页面里重复出现的行——页眉、页脚、水印都长这样。

    局限：只能抓"完全相同"的行，页码这类每页数字不同的要靠正则。
    """
    counter: Counter[str] = Counter()
    for text in pages:
        seen = {line.strip() for line in text.splitlines() if 2 <= len(line.strip()) <= 60}
        counter.update(seen)

    threshold = max(min_pages, int(len(pages) * ratio))
    return {line for line, count in counter.items() if count >= threshold}


def table_bbox(table) -> pymupdf.Rect | None:
    """把表格所有单元格矩形并成一个包围盒。"""
    rects = [r for row in table.rows for r in row.cells if r is not None]
    if not rects:
        return None
    box = pymupdf.Rect(rects[0])
    for r in rects[1:]:
        box |= pymupdf.Rect(r)
    return box


def table_to_rows(page: pymupdf.Page, table) -> list[list[str]]:
    """按单元格矩形重新取文本，让 PyMuPDF 按坐标排序（标点归位的关键）。"""
    rows: list[list[str]] = []
    for row in table.rows:
        cells = [
            "" if rect is None else page.get_text("text", clip=rect, sort=True)
            for rect in row.cells
        ]
        rows.append(cells)
    return rows


def rows_to_markdown(rows: list[list[str]]) -> str:
    """表格转 Markdown。Markdown 是给 LLM 读表格最稳的格式。"""
    if not rows:
        return ""

    width = max(len(r) for r in rows)
    norm: list[list[str]] = []
    for r in rows:
        cells = [clean_text(c, flatten=True) for c in r]
        cells += [""] * (width - len(cells))
        norm.append([c.replace("|", "\\|") for c in cells])

    header, *body = norm
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    lines += ["| " + " | ".join(r) + " |" for r in body]
    return "\n".join(lines)


def prose_blocks(page: pymupdf.Page, table_boxes: list[pymupdf.Rect]) -> list[str]:
    """取正文块，跳过落在表格区域内的块。"""
    out: list[str] = []
    for block in page.get_text("blocks"):
        x0, y0, x1, y1, text, _no, btype = block
        if btype != 0:  # 0 = 文本块，1 = 图片块
            continue
        rect = pymupdf.Rect(x0, y0, x1, y1)
        area = rect.get_area() or 1.0
        if any((rect & box).get_area() > area * 0.5 for box in table_boxes):
            continue
        out.append(text)
    return out


def parse_pdf(path: Path) -> tuple[list[dict], dict]:
    doc = pymupdf.open(path)
    raw_pages = [page.get_text("text") for page in doc]
    noise = detect_noise_lines(raw_pages)

    records: list[dict] = []
    dropped = 0

    for i, page in enumerate(doc):
        # --- 先处理表格，拿到区域和 Markdown ---
        tables: list[dict] = []
        boxes: list[pymupdf.Rect] = []
        try:
            for t in page.find_tables().tables:
                box = table_bbox(t)
                rows = table_to_rows(page, t)
                if not rows:
                    continue
                if box is not None:
                    boxes.append(box)
                tables.append(
                    {
                        "rows": len(rows),
                        "cols": max(len(r) for r in rows),
                        "markdown": rows_to_markdown(rows),
                    }
                )
        except Exception:  # 单页失败不该中断整份文档
            pass

        # --- 再取正文，跳过表格区域 ---
        kept: list[str] = []
        for chunk in prose_blocks(page, boxes):
            for line in chunk.splitlines():
                s = line.strip()
                if not s:
                    continue
                if s in noise or PAGE_NUM_RE.match(s):
                    dropped += 1
                    continue
                kept.append(s)

        records.append(
            {
                "page": i + 1,
                "text": clean_text("\n".join(kept)),
                "tables": tables,
            }
        )

    stats = {
        "pages": doc.page_count,
        "noise_lines": len(noise),
        "dropped_lines": dropped,
        "tables": sum(len(r["tables"]) for r in records),
        "chars": sum(len(r["text"]) for r in records),
        "table_chars": sum(len(t["markdown"]) for r in records for t in r["tables"]),
    }
    doc.close()
    return records, stats


def main() -> None:
    if len(sys.argv) < 2:
        print("用法：python -m pipeline.parser <pdf> [out.jsonl]")
        raise SystemExit(1)

    src = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_suffix(".jsonl")

    records, stats = parse_pdf(src)

    with out.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print("=" * 56)
    print(f"页数        : {stats['pages']}")
    print(f"表格        : {stats['tables']} 个")
    print(f"正文字符    : {stats['chars']}")
    print(f"表格字符    : {stats['table_chars']}")
    print(f"剔除噪声行  : {stats['dropped_lines']}")
    print("=" * 56)
    print("\n第 4 页正文（已排除表格）：")
    print("-" * 56)
    print(records[3]["text"][:500])
    print("-" * 56)


if __name__ == "__main__":
    main()
