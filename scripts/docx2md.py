r"""plan.docx → markdown 转换（架构 §8.1：python-docx 遍历段落+表格，表密集须完整转表）。

用法：server\.venv\Scripts\python.exe scripts\docx2md.py
输出：data\plan.md（运行时中间产物，data/ 不入库）
"""
import sys
from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "assets" / "august_fatloss" / "plan.docx"
OUT = ROOT / "data" / "plan.md"

# docx 样式名 → md 标题级
HEADING_MAP = {
    "Heading 1": "#", "Heading 2": "##", "Heading 3": "###", "Heading 4": "####",
    "标题 1": "#", "标题 2": "##", "标题 3": "###", "标题 4": "####",
}


def cell_text(cell) -> str:
    t = cell.text.strip().replace("\n", " ").replace("|", "\\|")
    return t if t else " "


def table_to_md(tbl: Table) -> str:
    rows = [[cell_text(c) for c in row.cells] for row in tbl.rows]
    if not rows:
        return ""
    n = max(len(r) for r in rows)
    rows = [r + [" "] * (n - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * n]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    doc = Document(SRC)
    out: list[str] = []
    n_para = n_tbl = 0
    for block in doc.iter_inner_content():
        if isinstance(block, Paragraph):
            text = block.text.strip()
            if not text:
                continue
            style = block.style.name if block.style is not None else ""
            prefix = HEADING_MAP.get(style)
            out.append(f"{prefix} {text}" if prefix else text)
            n_para += 1
        elif isinstance(block, Table):
            md = table_to_md(block)
            if md:
                out.append(md)
                n_tbl += 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n\n".join(out) + "\n", encoding="utf-8")
    print(f"转换完成：{n_para} 段落 + {n_tbl} 表格 → {OUT}（{OUT.stat().st_size} 字节）")


if __name__ == "__main__":
    main()
