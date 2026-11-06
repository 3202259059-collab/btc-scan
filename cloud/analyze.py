#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把行情快照 + 新闻交给 LLM，产出 ≤400 字的固定格式报告

未配置 LLM_API_KEY 时退化为纯数据 + 头条的简版报告（仍可推送）。
"""
import json
import os
import re
import sys
import urllib.error
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
        for host in ("https://models.github.ai/inference",
                     "https://models.inference.ai.azure.com"):
            yield (f"github-models:{host.split('//')[1].split('/')[0]}", host,
                   os.environ.get("GH_MODEL", "openai/gpt-4o-mini"), os.environ["GITHUB_TOKEN"])
    yield ("pollinations", "https://text.pollinations.ai/openai", "openai", None)


def _call_llm(messages, timeout=90):
    errors = []
    for name, base, model, key in _providers():
        try:
            body = json.dumps({"model": model, "messages": messages,
                               "temperature": 0.3, "max_tokens": 2000}).encode()
            headers = {"Content-Type": "application/json"}
            if key:
                headers["Authorization"] = f"Bearer {key}"
            req = urllib.request.Request(base + "/chat/completions", data=body, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    raw = r.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]!r}")
            text = ""
            try:
                out = json.loads(raw)
                text = (out["choices"][0]["message"]["content"] or "").strip()
            except json.JSONDecodeError:
                # 兼容纯文本 / SSE 流式返回
                if raw.lstrip().startswith("data:"):
                    parts = []
                    for line in raw.splitlines():
                        if not line.startswith("data:"):
                            continue
                        chunk = line[5:].strip()
                        if not chunk or chunk == "[DONE]":
                            continue
                        try:
                            j = json.loads(chunk)
                            parts.append(j["choices"][0].get("delta", {}).get("content") or "")
                        except Exception:  # noqa: BLE001
                            pass
                    text = "".join(parts).strip()
                else:
                    text = raw.strip()
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




BEAR_WORDS = [
    ("被盗", 3), ("黑客", 3), ("hack", 3), ("exploit", 3), ("攻击", 2),
    ("流出", 2), ("outflow", 2), ("抛售", 2), ("selloff", 2), ("抛压", 2),
    ("暴跌", 2), ("大跌", 2), ("plunge", 2), ("crash", 2), ("跳水", 2),
    ("清算", 2), ("liquidation", 2), ("爆仓", 2),
    ("监管", 1), ("regulation", 1), ("调查", 1), ("诉讼", 2), ("lawsuit", 2),
    ("加息", 2), ("hike", 2), ("通胀", 1), ("inflation", 1),
    ("冲突", 2), ("war", 2), ("制裁", 2), ("sanction", 2),
]
BULL_WORDS = [
    ("流入", 2), ("inflow", 2), ("净买入", 2), ("增持", 2), ("accumulate", 2),
    ("批准", 2), ("approve", 2), ("获批", 2), ("降息", 2), ("rate cut", 2),
    ("抄底", 2), ("buy the dip", 2), ("合作", 1), ("采用", 1), ("adoption", 1),
]
IMPL_BEAR = {"宏观": "压制风险资产估值，反弹乏力", "加密行业": "增量资金缺席，反弹受限",
             "美股联动": "风险偏好收缩，BTC 联动承压", "链上衍生品": "杠杆出清，短线波动放大"}
IMPL_BULL = {"宏观": "流动性预期改善，托底风险资产", "加密行业": "资金面改善，支撑反弹",
             "美股联动": "风险偏好修复，带动 BTC", "链上衍生品": "杠杆健康，回调有承接"}


def _score(title):
    t = title.lower()
    return (sum(w for k, w in BEAR_WORDS if k in t)
            - sum(w for k, w in BULL_WORDS if k in t))


def _clip(text, n=32):
    text = text.replace("\n", " ").strip()
    return text if len(text) <= n else text[:n] + "…"


def _rule_report(snap, items):
    """无 LLM 时的规则版：标题关键词打分 + 行情数据，保证格式完整"""
    now = datetime.strptime(snap["time_cst"], "%Y-%m-%d %H:%M:%S")
    b, o, f = snap["btc"], snap["oi"], snap["funding"]

    scored = []
    for topic, rows in items.items():
        for r in rows:
            if r.get("source") == "ERR":
                continue
            sc = _score(r["title"])
            if sc:
                scored.append((sc, topic, r))
    scored.sort(key=lambda x: -x[0])
    bears = [x for x in scored if x[0] > 0][:3]
    bulls = [x for x in scored if x[0] < 0][:2]

    def line(icon, weight, item, bull):
        _, topic, r = item
        impl = (IMPL_BULL if bull else IMPL_BEAR).get(topic, "")
        return f"{icon} {weight}：{_clip(r['title'])}｜{impl}"

    lines = [f"【BTC 消息面扫描】{now:%m-%d %H:%M}", "■ 利空（按权重）"]
    if bears:
        for i, it in enumerate(bears):
            lines.append(line(["🔴", "🟠", "🟡"][i], ["高", "中", "低"][i], it, False))
    else:
        lines.append(f"🟡 低：24h {b['chg24h_pct']:+.1f}%，价格位于 4H SuperTrend 下方｜趋势仍偏弱")

    lines.append("■ 利好（按权重）")
    if bulls:
        lines.append(line("🟢", "高", bulls[0], True))
    a = snap["ahr999"]["value"]
    zone = "抄底区" if a < 0.45 else ("定投区" if a < 1.2 else "泡沫区")
    lines.append(f"🟢 中：AHR999 {a:.3f} 处{zone}，RSI {snap['rsi4h']:.1f}，"
                 f"费率 {f['rate_pct']:+.4f}% 不拥挤｜下行有估值支撑")

    nb, nbl = len(bears), max(len(bulls), 1)
    bias = "偏空" if nb >= nbl else "偏多"
    lines.append(f"■ 净评估：短期{bias} {max(nb,1)}:{max(nbl,0)}")

    res, sup = snap["levels"]["resistance"], snap["levels"]["support"]
    lv = []
    if res:
        lv.append(f"阻 {res['value']:,.0f}（{res['name']}）")
    if sup:
        lv.append(f"撑 {sup['value']:,.0f}（{sup['name']}）")
    lines.append(f"■ 现价 {b['last']:,.0f}｜" + "｜".join(lv))

    chg = o["oi_chg24h_pct"]
    oi_txt = f"■ 持仓量 {o['oi_btc']:,.0f} BTC（{chg:+.1f}%）" if chg is not None else f"■ 持仓量 {o['oi_btc']:,.0f} BTC"
    lines.append(oi_txt + f"→ 波动预警：{'有' if snap['vol_alert'] else '无'}")

    text_all = " ".join(r["title"] for rows in items.values() for r in rows)
    cat = None
    for kw, name, default in (("非农", "美国 10 月非农", "21:30"), ("CPI", "美国 CPI", "20:30")):
        if kw in text_all:
            for rows in items.values():
                for r in rows:
                    if kw in r["title"]:
                        m = re.search(r"(\d{1,2}[:：]\d{2})", r["title"])
                        cat = f"{m.group(1) if m else default} {name}"
                        break
                if cat:
                    break
            break
    if not cat:
        ft = datetime.fromtimestamp(f["funding_ts"] / 1000)
        cat = f"{ft:%H:%M} 资金费率结算"
    lines.append(f"■ 下一个催化：{cat}")

    lines.append(f"■ 风险提示：消息驱动为主，警惕插针；非农前后波动放大")
    return "\n".join(lines)


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
        text = _call_llm([{"role": "system", "content": SYSTEM},
                          {"role": "user", "content": prompt}])
        if len(text) >= 100 and "【" in text:
            return text
        print(f"[analyze] llm output invalid ({len(text)} chars)", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"[analyze] llm failed: {e}", file=sys.stderr)
    return _rule_report(snap, items)


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
