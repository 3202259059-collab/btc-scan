#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""四个方向新闻抓取：Google News RSS（中英各一次），无 API key"""
import email.utils
import html
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) btc-scan/2.0"}

TOPICS = {
    "宏观": {
        "en": "Federal Reserve OR CPI OR nonfarm payrolls OR dollar index",
        "zh": "美联储 OR 非农 OR 油价 OR 美元指数",
    },
    "加密行业": {
        "en": "Bitcoin ETF OR crypto exchange hack OR crypto regulation",
        "zh": "比特币ETF OR 交易所被盗 OR 加密监管",
    },
    "美股联动": {
        "en": "Nvidia OR Nasdaq OR AI capex",
        "zh": "英伟达 OR 纳指 OR AI资本开支",
    },
    "链上衍生品": {
        "en": "Bitcoin whale OR crypto liquidation OR funding rate",
        "zh": "比特币巨鲸 OR 加密清算 OR 资金费率",
    },
}


def _rss(query, lang, limit=8):
    if lang == "zh":
        params = {"q": query, "hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"}
    else:
        params = {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=15) as r:
        root = ET.fromstring(r.read())
    out = []
    for it in root.findall(".//item")[:limit * 2]:
        title = html.unescape(it.findtext("title") or "").strip()
        if not title:
            continue
        try:
            dt = email.utils.parsedate_to_datetime(it.findtext("pubDate") or "")
            dt = dt.astimezone(CST)
        except Exception:  # noqa: BLE001
            continue
        src = (it.findtext("source") or "").strip()
        # 去掉标题末尾的 " - 来源"
        clean = re.sub(r"\s+-\s+[^-]{2,40}$", "", title).strip()
        out.append({"title": clean, "source": src or "GoogleNews", "time": dt,
                    "link": it.findtext("link") or ""})
    return out


def fetch(hours=24):
    """返回 {topic: [{title, source, time, lang}]}，仅保留近 N 小时"""
    cutoff = datetime.now(CST) - timedelta(hours=hours)
    seen, result = set(), {}
    for topic, q in TOPICS.items():
        rows = []
        for lang in ("en", "zh"):
            try:
                for it in _rss(q[lang], lang):
                    if it["time"] < cutoff:
                        continue
                    key = re.sub(r"\W+", "", it["title"].lower())[:40]
                    if key in seen:
                        continue
                    seen.add(key)
                    it["lang"] = lang
                    rows.append(it)
            except Exception as e:  # noqa: BLE001
                rows.append({"title": f"[{lang} 检索失败: {e}]", "source": "ERR",
                             "time": datetime.now(CST), "lang": lang, "link": ""})
            time.sleep(0.3)
        rows.sort(key=lambda x: x["time"], reverse=True)
        result[topic] = rows[:6]
    return result


if __name__ == "__main__":
    data = fetch()
    for t, rows in data.items():
        print(f"\n## {t}")
        for r in rows:
            print(f"  [{r['lang']}] {r['time']:%m-%d %H:%M} {r['title'][:70]} | {r['source']}")
