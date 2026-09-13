r"""P0 验收测试（架构 §10-P0 验收标准）。

1. /api/health 正常
2. xlsx 真实 4 行（35 条）经 API 可见（"时间线可见"的后端等价）
3. 手动添加一条晨重（今天 106.4kg，即 xlsx 9-04 行——按 §8.2 未导入，走新站链路）→ 立即可查
4. 约束闸：700kg 被拒；非法奶茶档位被拒；相对 ±5kg 超限返回 warning
"""
import json
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
BASE = "http://127.0.0.1:8001/api"
ok_all = True


def call(method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(
        BASE + path,
        method=method,
        data=json.dumps(body).encode() if body else None,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def check(name: str, cond: bool, detail: str = ""):
    global ok_all
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    ok_all = ok_all and cond


# 1. 健康检查
st, body = call("GET", "/health")
check("GET /api/health", st == 200 and body.get("app") == "康迹", str(body))

# 2. 迁移数据可见
st, records = call("GET", "/records")
check("迁移 records 可见（35 条）", st == 200 and len(records) == 35, f"{len(records)} 条")
dates = sorted({r["date"] for r in records})
check("日期覆盖 8-31~9-03", dates == ["2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03"], str(dates))
sweet = [r for r in records if r["type"] == "sweet_drink"]
levels = {r["date"]: r["fields"]["level"] for r in sweet}
check("奶茶档位推断（可乐→全糖）", levels.get("2026-09-01") == "全糖", str(levels))

# 3. 手动入账今天的晨重（新站链路）
st, body = call(
    "POST", "/records",
    {"type": "weight", "date": "2026-09-04", "slot": "am",
     "fields": {"kg": 106.4}, "raw_text": "今早空腹 106.4", "source": "manual"},
)
check("手动添加今日晨重 106.4", st == 200 and body.get("fields", {}).get("kg") == 106.4
      and body.get("source") == "manual", str(body)[:120])

st, today = call("GET", "/records?date=2026-09-04")
check("当日时间线立即可见", st == 200 and len(today) == 1 and today[0]["slot"] == "am",
      f"{len(today)} 条")

# 4. 约束闸
st, body = call(
    "POST", "/records",
    {"type": "weight", "date": "2026-09-04", "slot": "evening", "fields": {"kg": 700}},
)
check("绝对闸：700kg 被拒(422)", st == 422, f"status={st}")

st, body = call(
    "POST", "/records",
    {"type": "sweet_drink", "date": "2026-09-04", "fields": {"level": "超多糖"}},
)
check("枚举闸：非法奶茶档位被拒(422)", st == 422, f"status={st}")

st, body = call(
    "POST", "/records",
    {"type": "weight", "date": "2026-09-04", "slot": "am", "fields": {"kg": 130}},
)
check("相对闸：+23.6kg 不硬拒但给 warning", st == 200 and len(body.get("warnings", [])) == 1,
      str(body.get("warnings")))

# 清理测试数据（保留 106.4 晨重作为今日基线，删除 130 测试项）
if st == 200 and "id" in body:
    call("DELETE", f"/records/{body['id']}")

print()
print("P0 验收：" + ("全部通过" if ok_all else "存在失败项"))
sys.exit(0 if ok_all else 1)
