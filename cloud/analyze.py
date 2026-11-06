#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把行情快照 + 新闻交给 LLM，产出 ≤400 字的固定格式报告

未配置 LLM_API_KEY 时退化为纯数据 + 头条的简版报告（仍可推送）。
"""
import json
import os
import sys
import urllib.request
from datetime import datetime

TZ_NAME = "Asia/Shanghai"

SYSTEM = (
    "你是加密货币市场分析师。只输出报告正文，不要解释、不要前后缀。"
    "严格使用给定格式，全文不超过 400 个汉字。所有价格/持仓/指标数字只能引用输入数据，"
    "不得编造；新闻只引用输入头条，忽略与四个方向无关的噪音。"
    "权重按对 BTC 短期（1-3 天）价格的影响排序，利空与利好各不超过 3 条。"
)

TEMPLATE = """【BTC 消息面扫描】{mmdd} {hhmm}
■ 利空（按权重）
🔴 高：一句话 + 对价格的含义
🟠 中：一句话
🟡 低：一句话
■ 利好（按权重）
🟢 高：一句话
🟢 中：一句话
■ 净评估：短期偏空/偏多 x:y
■ 现价 {px} | 关键位 xxx（注明是哪个指标）
■ 持仓量 {oi}（变化）→ 波动预警：有/无
■ 下一个催化：时间 + 事件
■ 风险提示一行"""


def _providers():
    """按优先级给出可用的 LLM 通道：自己的 key > GitHub Models > 免费匿名"""
    if os.environ.get("LLM_API_KEY"):
        yield ("llm", os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1").rstrip("/"),
               os.environ.get("LLM_MODEL", "deepseek-chat"), os.environ["LLM_API_KEY"])
    if os.environ.get("GITHUB_TOKEN"):
        yield ("github-models", "https://models.github.ai/inference",
               os.environ.get("GH_MODEL", "openai/gpt-4o-mini"), os.environ["GITHUB_TOKEN"])
    yield ("pollinations", "https://text.pollinations.ai/openai", "openai", None)


def _call_llm(messages, timeout=90):
    errors = []
    for name, base, model, key in _providers():
        try:
            body = json.dumps({"model": model, "messages": messages,
                               "temperature": 0.3, "max_tokens": 900}).encode()
            headers = {"Content-Type": "application/json"}
            if key:
                headers["Authorization"] = f"Bearer {key}"
            req = urllib.request.Request(base + "/chat/completions", data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                out = json.load(r)
            text = (out["choices"][0]["message"]["content"] or "").strip()
            if text:
                if name != "llm":
                    print(f"[analyze] provider={name}", file=sys.stderr)
                return text
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}:{str(e)[:80]}")
    raise RuntimeError("all LLM providers failed: " + " | ".join(errors))


def _digest(snap, items):
    d = {
        "时间": snap["time_cst"],
        "BTC": {"现价": round(snap["btc"]["last"]),
                "24h涨跌%": round(snap["btc"]["chg24h_pct"], 2),
                "24h高": round(snap["btc"]["high24h"]), "24h低": round(snap["btc"]["low24h"])},
        "持仓量": {"BTC": round(snap["oi"]["oi_btc"]),
                   "24h变化%": None if snap["oi"]["oi_chg24h_pct"] is None else round(snap["oi"]["oi_chg24h_pct"], 2)},
        "资金费率": {"当期%": round(snap["funding"]["rate_pct"], 4),
                     "年化%": round(snap["funding"]["annual_pct"], 2),
                     "下次结算": datetime.fromtimestamp(snap["funding"]["funding_ts"] / 1000).strftime("%m-%d %H:%M")},
        "4H_RSI": round(snap["rsi4h"], 1),
        "4H_SuperTrend": {"值": round(snap["supertrend4h"]["value"]), "方向": snap["supertrend4h"]["direction"]},
        "日线EMA": {k: round(v) for k, v in snap["ema_daily"].items()},
        "AHR999": round(snap["ahr999"]["value"], 3),
        "关键位": snap["levels"],
        "跨资产24h%": {k: round(v["chg24h_pct"], 2) for k, v in snap["cross"].items()},
        "24h波动小于1%": snap["flat_market"],
        "波动预警": snap["vol_alert"],
    }
    lines = []
    for topic, rows in items.items():
        lines.append(f"## {topic}")
        for r in rows[:5]:
            lines.append(f"- [{r['time']:%m-%d %H:%M}] {r['title']}（{r['source']}）")
    return json.dumps(d, ensure_ascii=False), "\n".join(lines)


def build(snap, items):
    data_json, headlines = _digest(snap, items)
    now = datetime.strptime(snap["time_cst"], "%Y-%m-%d %H:%M:%S")
    header = TEMPLATE.format(mmdd=now.strftime("%m-%d"), hhmm=now.strftime("%H:%M"),
                             px=f"{snap['btc']['last']:,.0f}",
                             oi=f"{snap['oi']['oi_btc']:,.0f} BTC")

    prompt = f"""以下是刚采集的行情数据（OKX）与过去 24 小时新闻头条。

【行情】
{data_json}

【新闻】
{headlines}

要求：
1. 按下面模板输出，占位符 xxx 必须替换成真实内容；标题时间用 {now:%m-%d %H:%M}。
2. 利空 3 条封顶、利好 2 条封顶，每条一句话；高权重那条要写"对价格的含义"。
3. 净评估给 x:y（利空:利好 的权重比），并判断短期偏空/偏多。
4. 关键位从"关键位"字段里选最近的阻力/支撑，注明指标名。
5. 持仓量写 BTC 数量 + 24h 变化方向；波动预警按"波动预警"字段。
6. 下一个催化：从新闻里找最近的有明确时间的事件；找不到就写资金费率结算时间。
7. 若"24h波动小于1%"为 true 且四条线都没有实质新消息，只输出一行：无重大变化 | 现价 xxx。
8. 全文 ≤400 汉字，不要 Markdown 表格、不要额外说明。

模板：
{header}"""
    try:
        return _call_llm([{"role": "system", "content": SYSTEM},
                          {"role": "user", "content": prompt}])
    except Exception as e:  # noqa: BLE001
        print(f"[analyze] fallback: {e}", file=sys.stderr)
        return _fallback(snap, items)


def _fallback(snap, items):
    b, o = snap["btc"], snap["oi"]
    now = datetime.strptime(snap["time_cst"], "%Y-%m-%d %H:%M:%S")
    lines = [f"【BTC 消息面扫描】{now:%m-%d %H:%M}"]
    lines.append(f"■ 利空：数据模式（未配置 LLM），24h {b['chg24h_pct']:+.2f}%")
    for topic, rows in items.items():
        if rows and rows[0]["source"] != "ERR":
            lines.append(f"🟡 {topic}：{rows[0]['title'][:40]}")
    lines.append(f"■ 利好：AHR999 {snap['ahr999']['value']:.3f}，4H RSI {snap['rsi4h']:.1f}")
    lines.append(f"■ 净评估：短期{'偏空' if b['chg24h_pct'] < 0 else '偏多'}（待 LLM 分析）")
    lv = snap["levels"]["support"]
    if lv:
        lines.append(f"■ 支撑 {lv['value']:,.0f}（{lv['name']}）")
    lines.append(f"■ 持仓量 {o['oi_btc']:,.0f} BTC（{o['oi_chg24h_pct']:+.2f}%）→ 波动预警：{'有' if snap['vol_alert'] else '无'}"
                 if o["oi_chg24h_pct"] is not None else
                 f"■ 持仓量 {o['oi_btc']:,.0f} BTC → 波动预警：{'有' if snap['vol_alert'] else '无'}")
    lines.append("■ 风险提示：未配置 LLM，本条仅为数据播报")
    return "\n".join(lines)
