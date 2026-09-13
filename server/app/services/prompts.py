"""系统提示组装（架构 §6.1 管线 ①②③④）。

分层：静态人格与边界 → 用户档案（真实画像，8 月主线口径）→ 动态上下文（近 3 日）→ 知识库命中。
"""
from datetime import date, timedelta
from typing import Iterable

from app.models import Record

# 注：不使用模块级 TODAY 常量——跨零点后会过期，日期一律按请求时计算

# ---------- ① 静态层：人格 + 边界 + 工具纪律（§6.6 医疗红线全文进提示） ----------
STATIC_PROMPT = """你是「康迹」的 AI 健康助理，服务唯一用户本人。语气：简短、务实、像靠谱的老友，不说教不铺垫。

## 核心工作方式
1. 用户用一句话说日常记录（体重/三餐/奶茶甜饮/夜饿/游泳/力量/步数/入睡/补剂/不适/备注），你**必须调用 register_record 工具**抽取结构化记录。一句话含多个记录就多次调用。
   **铁律：没有卡片就没有记录。**绝对禁止只在回复文字里描述"已记下"而不调用工具。
2. 记录未经用户在确认卡片上点确认前，绝不视为已入账。**判断是否重复的唯一依据是下方动态上下文里的"今日已入账"清单，而不是对话历史里你曾经说过什么**——历史中生成过但未出现在清单里的记录，说明用户没确认，不算已入账，可直接重新生成卡片。发现清单里已有同类记录时，先提示"今日X已记录为Y，是要修改吗？"再决定。
3. 日期默认今天（跨零点规则：入睡时间若在 0:00-12:00 视为昨晚，日期归前一日）。
4. 回答涉及方案的问题（剂量/菜单/阶段/行动/监测信号）时，必须引用知识库原文并注明来源文件与章节号；知识库没有的内容不得编造，明说"方案里没有，我记下来待补充"或建议就医。
5. 周复盘/趋势/进展类问题（"这周怎么样""复盘一下""趋势如何"）→ 先调 get_trend 工具拿周报数据再回答：对照达标口径（每周 -0.5~-1.5kg，plan §5.2）给出评价，点名奶茶/夜宵/步数/游泳的具体表现，末尾给一句下周可执行的改进点；若动态上下文列出了异常信号，必须提及并注明来源（06-监测.md §二）。

## 两代方案分域（最高纪律，违反即事故）
- 减脂执行、阶段、目标、热量、血糖稳定化：以【8月主线方案 plan.docx】为准（两阶段：冲刺期8.31-9.20 / 稳态期9.21+；基线108.55kg）。
- 补剂剂量、激素、中医、就医红线：以【7月健康知识库】为准（VitD3 2000IU 早餐后 / 锌15-25mg 晚餐后 / 长期补锌+1-2mg铜）。
- 严禁用7月的三阶段/100kg基线解释当前记录；严禁用8月方案回答补剂细节。

## 医疗红线（不可逾越）
- 本工具只做记录与生活方式管理，不做疾病诊断、不给处方级建议。
- 腰突/踝/肠胃症状持续或加重 → 一律"建议线下就医"；肠胃不适连续3天以上提示就医。
- 补剂只引用 01-激素平衡与抗雌化.md §三原文；方案明列"暂不推荐"的蛋白粉/肌酸/促睾一律拒答并提示就医/问诊。
- 中药方剂 → "先经中医师面诊确认体质"，不自行给方。
- 血糖相关风险（低血糖等）对齐 plan.docx §6.1：立即吃糖并告知他人。"""

# ---------- ② 档案层：真实画像（8 月主线口径，§6.1） ----------
PROFILE_PROMPT = """## 用户档案（当前主线：8月减脂作战方案）
- 基线（2026-08-30）：晨重 108.55kg，BMI 35.4，腰围 110cm
- 阶段：冲刺期 2026-08-31 ~ 09-20（3周）；之后稳态期（9-21 开学）
- 3周目标（9-20）：约 104-105kg / 腰围 107-108；长期目标：约 93-95kg / 腰围 102-104
- 核心策略：血糖稳定化（防暴食）；三座大山：奶茶、夜宵、零食
- 身体约束：腰突+腰肌劳损（护腰、弃跳）；踝关节有伤（零跳跃）；早饱/胃胀/易饿
- 运动：游泳为主力（每周4次 45-60min）+ 居家力量（每周2次，零跳跃护腰护踝）
- 补剂（7月KB口径）：VitD3 2000IU 早餐后 / 锌 15-25mg 晚餐后 / 长期补锌 +1-2mg 铜"""


def _fmt_record(r: Record) -> str:
    f = r.fields_json or {}
    slot = f"[{r.slot}] " if r.slot else ""
    if r.type == "weight":
        detail = f"{f.get('kg')}kg"
    elif r.type == "sleep":
        detail = f"{f.get('bedtime')} 入睡"
    elif r.type == "meal":
        detail = str(f.get("desc", ""))[:40]
    elif r.type == "sweet_drink":
        detail = f"{f.get('level')}" + (f"（{f.get('desc')}）" if f.get("desc") else "")
    elif r.type == "exercise":
        detail = (f"游泳{f.get('duration_min')}min" if f.get("kind") == "swim"
                  else f"力量{'完成' if f.get('done') else '未做'}")
    elif r.type == "step":
        detail = f"{f.get('steps')} 步"
    elif r.type == "waist":
        detail = f"腰围 {f.get('cm')}cm"
    elif r.type == "night_hunger":
        detail = f"夜饿处理：{f.get('level')}"
    elif r.type == "supplement":
        item = {"vitd3": "维D3", "zinc": "锌", "copper": "铜"}.get(f.get("item"), f.get("item"))
        detail = f"{item} {'已吃' if f.get('taken', True) else '没吃'}"
    else:
        detail = str(f)[:60]
    return f"- {r.date} {r.type} {slot}{detail}"


def build_dynamic_context(recent_records: Iterable[Record], today: date) -> str:
    """③ 动态上下文：近 3 日摘要 + 当日已入账清单（防重复入账） + 异常信号（§6.7）。"""
    lines = [f"## 动态上下文（今天：{today.isoformat()}）"]
    today_items = [r for r in recent_records if r.date == today]
    # 摘要只取近 3 日；完整窗口（21 日）仅供异常信号检测用，不入摘要避免 prompt 膨胀
    since_3d = today - timedelta(days=3)
    past_items = [r for r in recent_records if since_3d <= r.date < today]
    if past_items:
        lines.append("近3日已入账：")
        lines.extend(_fmt_record(r) for r in past_items)
    else:
        lines.append("近3日无记录。")
    if today_items:
        lines.append("今日已入账（勿重复生成，除非用户明确要改）：")
        lines.extend(_fmt_record(r) for r in today_items)
    else:
        lines.append("今日尚无记录。")

    signals = _adjustment_signals(recent_records, today)
    if signals:
        lines.append("异常信号（对齐 06-监测与调整.md §二，提及时注明依据）：")
        lines.extend(f"- {s}" for s in signals)
    return "\n".join(lines)


def _adjustment_signals(recent_records: Iterable[Record], today: date) -> list[str]:
    """§6.7 异常识别：体重连续2周不变 / 肠胃不适连续3天。"""
    records = list(recent_records)
    signals: list[str] = []

    # 肠胃不适连续 ≥3 天（body site=肠胃）
    gi_dates = sorted(
        {
            r.date
            for r in records
            if r.type == "body" and (r.fields_json or {}).get("site") == "肠胃"
        },
        reverse=True,
    )
    if gi_dates:
        streak = 1
        for prev, cur in zip(gi_dates, gi_dates[1:]):
            if (prev - cur).days == 1:
                streak += 1
            else:
                break
        if streak >= 3:
            signals.append(
                f"肠胃不适已连续 {streak} 天（最近 {gi_dates[0]}）→ 提示当天回退温和饮食，连续 3 天以上建议就医（06-监测.md §二）"
            )

    # 体重连续 2 周不变（需 ≥15 天数据且首尾周均差 <0.3kg）
    am: dict[date, float] = {}
    for r in records:
        if r.type == "weight" and r.slot == "am":
            kg = (r.fields_json or {}).get("kg")
            if isinstance(kg, (int, float)):
                am[r.date] = float(kg)
    if len(am) >= 15:
        sorted_d = sorted(am)
        span = (sorted_d[-1] - sorted_d[0]).days
        first_w = [d for d in sorted_d if d <= sorted_d[0] + timedelta(days=6)]
        last_w = [d for d in sorted_d if d > sorted_d[-1] - timedelta(days=7)]
        first_avg = sum(am[d] for d in first_w) / len(first_w)
        last_avg = sum(am[d] for d in last_w) / len(last_w)
        if span >= 14 and abs(last_avg - first_avg) < 0.3:
            signals.append(
                f"晨重近 2 周基本持平（{first_avg:.1f}→{last_avg:.1f}）→ 检查隐性热量（奶茶/夜宵/零食），适当增加有氧（06-监测.md §二）"
            )
    return signals


def build_system_prompt(
    recent_records: Iterable[Record],
    kb_context: str,
    today: date | None = None,
) -> str:
    """today 不传则按当前时间计算（不用模块常量，避免跨零点过期）。"""
    if today is None:
        today = date.today()
    return "\n\n".join(
        [
            STATIC_PROMPT,
            PROFILE_PROMPT,
            build_dynamic_context(recent_records, today),
            "## 知识库命中（本轮检索 top-5，引用时注明来源）\n" + kb_context,
        ]
    )
