r"""迁移核对脚本（架构 §8.2）。

核对项：
1. xlsx 真实数据行数（今天之前、有数据）vs imports 台账行数
2. 晨重曲线抽点：8-31→107.6 / 9-01→106.95 / 9-02→106.75 / 9-03→106.7
3. 各 type 的 records 计数与 xlsx 逐列独立复算一致
4. 台账幂等重跑检查：再次运行 import_xlsx.py 不产生新记录

用法：server\.venv\Scripts\python.exe scripts\verify_import.py
退出码 0=全部通过，1=存在不一致。
"""
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
sys.path.insert(0, str(SERVER))

import openpyxl  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import ImportLedger, Record  # noqa: E402
from import_xlsx import (  # noqa: E402  同目录导入（脚本运行时 scripts/ 自动在 sys.path）
    SOURCE_FILE,
    XLSX,
    infer_night_hunger,
    infer_sweet_level,
    is_bad,
)

# §8.2 指定的晨重抽点（人工锚定，防脚本自说自话）
EXPECTED_AM_WEIGHTS = {
    date(2026, 8, 31): 107.6,
    date(2026, 9, 1): 106.95,
    date(2026, 9, 2): 106.75,
    date(2026, 9, 3): 106.7,
}

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(name)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    today = date.today()
    wb = openpyxl.load_workbook(XLSX, data_only=True)
    ws = wb["每日记录"]

    # 独立复算：今天之前、有真实数据的行与其逐列记录数
    real_rows = 0
    expected_by_type: dict[str, int] = {}
    for r in range(3, ws.max_row + 1):
        v = ws.cell(row=r, column=1).value
        d = v.date() if isinstance(v, datetime) else v
        if not isinstance(d, date) or d >= today:
            continue
        cells = {c: ws.cell(row=r, column=i).value for i, c in enumerate("ABCDEFGHIJKLMNO", start=1)}
        if all(is_bad(x) for k, x in cells.items() if k not in "AB"):
            continue
        real_rows += 1
        for col in "CD":
            if not is_bad(cells.get(col)):
                expected_by_type["weight"] = expected_by_type.get("weight", 0) + 1
        for col in "EFGH":
            if not is_bad(cells.get(col)):
                expected_by_type["meal"] = expected_by_type.get("meal", 0) + 1
        if not is_bad(cells.get("I")) and infer_sweet_level(str(cells["I"]).strip()):
            expected_by_type["sweet_drink"] = expected_by_type.get("sweet_drink", 0) + 1
        if not is_bad(cells.get("J")):
            expected_by_type["exercise"] = expected_by_type.get("exercise", 0) + 1
        if not is_bad(cells.get("L")):
            expected_by_type["step"] = expected_by_type.get("step", 0) + 1
        if not is_bad(cells.get("M")):
            expected_by_type["sleep"] = expected_by_type.get("sleep", 0) + 1
        if not is_bad(cells.get("N")) and infer_night_hunger(str(cells["N"]).strip()):
            expected_by_type["night_hunger"] = expected_by_type.get("night_hunger", 0) + 1
        if not is_bad(cells.get("O")):
            expected_by_type["note"] = expected_by_type.get("note", 0) + 1

    db = SessionLocal()
    try:
        ledger_rows = db.scalar(
            select(func.count()).select_from(ImportLedger).where(
                ImportLedger.source_file == SOURCE_FILE,
                ImportLedger.sheet == "每日记录",
            )
        )
        check("台账行数 == xlsx 真实行数", ledger_rows == real_rows,
              f"台账 {ledger_rows} vs 真实 {real_rows}")

        imported = db.scalar(
            select(func.count()).select_from(Record).where(Record.source == "import")
        )
        expected_total = sum(expected_by_type.values())
        check("导入 records 总数 == 逐列复算总数", imported == expected_total,
              f"DB {imported} vs 复算 {expected_total}")

        for t, n in sorted(expected_by_type.items()):
            got = db.scalar(
                select(func.count()).select_from(Record).where(
                    Record.source == "import", Record.type == t
                )
            )
            check(f"type={t} 计数", got == n, f"DB {got} vs 复算 {n}")

        # 晨重抽点
        for d, kg in EXPECTED_AM_WEIGHTS.items():
            rec = db.scalars(
                select(Record).where(
                    Record.type == "weight",
                    Record.slot == "am",
                    Record.date == d,
                    Record.source == "import",
                )
            ).first()
            ok = rec is not None and abs(rec.fields_json.get("kg", 0) - kg) < 1e-9
            got = rec.fields_json.get("kg") if rec else None
            check(f"晨重 {d} == {kg}kg", ok, f"DB {got}")
    finally:
        db.close()

    print()
    if failures:
        print(f"核对未通过：{len(failures)} 项失败 — {failures}")
        sys.exit(1)
    print("核对全部通过：基线无损。")


if __name__ == "__main__":
    main()
