r"""知识库导入：md → kb_chunks（架构 §6.4/§8.1）。

- 7 月背景 KB：assets\july_health\ 的 00~07 编号 md + 健康管理计划.md + 补充.md
  （需求.md 是项目文档而非方案，不入 KB）
- 8 月主线：data\plan.md（由 scripts\docx2md.py 生成）
- 按标题层级切块（每块 ≈ 一个完整小节），记 section_no（如 3.4/5.2）
- 打标签（补剂/菜单/行动/监测/就医），source_plan 两代分域
- 幂等：同 (title, source_plan, version) 重跑时覆盖旧块（§6.4 版本化）

用法：
    server\.venv\Scripts\python.exe scripts\docx2md.py
    server\.venv\Scripts\python.exe scripts\import_kb.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
sys.path.insert(0, str(SERVER))

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import KbChunk, KbDoc  # noqa: E402

JULY_DIR = ROOT / "assets" / "july_health"
AUGUST_MD = ROOT / "data" / "plan.md"

# §6.4 源清单（不含 需求.md）
JULY_FILES = [
    "00-总览与阶段划分.md",
    "01-激素平衡与抗雌化.md",
    "02-身体调养与中医调理.md",
    "03-日常习惯养成.md",
    "04-日常锻炼.md",
    "05-日常饮食与一周菜单.md",
    "06-监测与调整.md",
    "07-第一周行动清单.md",
    "健康管理计划.md",
    "补充.md",
]

_HEADING_RE = re.compile(r"^(#{1,4})\s+(.*)$")
_SECTION_RE = re.compile(r"^(\d+(?:\.\d+)*)[、.\s]")

TAG_RULES = [
    ("补剂", r"补剂|维生素|VitD|维D|肌酸|蛋白粉|促睾|剂量|IU"),
    ("菜单", r"菜单|食谱|饮食|热量|千卡|吃什么|营养素|蛋白质|碳水"),
    ("行动", r"行动|清单|打卡|模板|习惯|执行|训练|游泳|力量"),
    ("监测", r"监测|记录|体重|腰围|复盘|指标|趋势|平台期|血糖"),
    ("就医", r"就医|医院|医生|就诊|红线|面诊|中医师"),
]


def extract_section_no(heading: str) -> str:
    m = _SECTION_RE.match(heading.strip())
    return m.group(1) if m else ""


def infer_tags(content: str) -> list[str]:
    tags = [tag for tag, pat in TAG_RULES if re.search(pat, content)]
    return tags


def chunk_md(md_text: str) -> list[dict]:
    """按标题切块；每块 = {heading, section_no, content}，文件级前言并入首块前的独立块。"""
    chunks: list[dict] = []
    current_heading = ""
    buf: list[str] = []

    def flush() -> None:
        text = "\n".join(buf).strip()
        if not text:
            return
        if current_heading or len(text) >= 20:
            chunks.append(
                {
                    "heading": current_heading,
                    "section_no": extract_section_no(current_heading),
                    "content": text,
                }
            )

    for line in md_text.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            flush()
            current_heading = m.group(2).strip()
            buf = [line]
        else:
            buf.append(line)
    flush()
    return chunks


def import_doc(db, path: Path, source_plan: str, version: str) -> int:
    doc_title = path.stem if source_plan == "august_fatloss" else path.name
    # plan.md 显示名与源文件对齐
    if source_plan == "august_fatloss":
        doc_title = "plan.docx"
    md = path.read_text(encoding="utf-8")
    doc = db.scalars(
        select(KbDoc).where(
            KbDoc.title == doc_title, KbDoc.source_plan == source_plan
        )
    ).first()
    if doc is None:
        doc = KbDoc(title=doc_title, source_plan=source_plan, version=version)
        db.add(doc)
        db.flush()
    else:
        doc.version = version
        for old in db.scalars(select(KbChunk).where(KbChunk.doc_id == doc.id)).all():
            db.delete(old)  # 覆盖重导（§6.4 版本化）
        db.flush()

    n = 0
    for ch in chunk_md(md):
        content_with_heading = (
            f"## {ch['heading']}\n\n{ch['content']}" if ch["heading"] else ch["content"]
        )
        db.add(
            KbChunk(
                doc_id=doc.id,
                title=doc_title,
                heading=ch["heading"][:250],
                source_plan=source_plan,
                section_no=ch["section_no"],
                content=content_with_heading,
                tags=infer_tags(content_with_heading),
            )
        )
        n += 1
    return n


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    db = SessionLocal()
    try:
        for name in JULY_FILES:
            p = JULY_DIR / name
            if not p.exists():
                print(f"[缺失] {name}")
                continue
            version = p.stat().st_mtime
            from datetime import datetime

            version = datetime.fromtimestamp(version).strftime("%Y-%m-%d")
            n = import_doc(db, p, "july_health", version)
            print(f"[july_health] {name}: {n} 块")

        if AUGUST_MD.exists():
            n = import_doc(db, AUGUST_MD, "august_fatloss", "2026-08-30")
            print(f"[august_fatloss] plan.docx: {n} 块")
        else:
            print("[提示] data\\plan.md 不存在，请先运行 scripts\\docx2md.py")
        db.commit()
        from sqlalchemy import func

        total = db.scalar(select(func.count()).select_from(KbChunk))
        by_plan = dict(
            db.execute(
                select(KbChunk.source_plan, func.count()).group_by(KbChunk.source_plan)
            ).all()
        )
        print(f"\n完成：kb_chunks 共 {total} 块，分域 {by_plan}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
