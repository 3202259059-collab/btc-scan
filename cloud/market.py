#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OKX 行情快照（纯 HTTP，无第三方依赖，云端可跑）

指标直接走 OKX 公共指标接口（与本地 okx CLI 同源，数值一致）：
  4H  RSI(14) / SuperTrend(10,3)
  1D  EMA20/50/200 / AHR999
"""
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

REST = ["https://app.okx.com", "https://www.okx.com"]  # 主域名慢/不通时自动切备用
CST = timezone(timedelta(hours=8))
UA = {"User-Agent": "Mozilla/5.0 btc-scan/2.0", "Content-Type": "application/json"}


def _request(method, path, params=None, body=None, retries=2, hosts=None):
    data = json.dumps(body).encode() if body is not None else None
    last = None
    for base in (hosts or REST):
        url = base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        for _ in range(retries + 1):
            try:
                req = urllib.request.Request(url, data=data, headers=UA, method=method)
                with urllib.request.urlopen(req, timeout=15) as r:
                    out = json.load(r)
                if out.get("code") == "0":
                    return out["data"]
                last = RuntimeError(f"OKX {base} code={out.get('code')} {out.get('msg')}")
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(0.5)
    raise last


def ticker(inst):
    d = _request("GET", "/api/v5/market/ticker", {"instId": inst})[0]
    last, op = float(d["last"]), float(d["open24h"])
    return {
        "last": last, "open24h": op,
        "high24h": float(d["high24h"]), "low24h": float(d["low24h"]),
        "chg24h_pct": (last - op) / op * 100 if op else 0.0,
    }


def indicators():
    """4H RSI/SuperTrend + 日线 EMA/AHR999，返回扁平字典"""
    # 指标接口只挂在 www 上（app.okx.com 返回 405），优先走 www
    IND = ["https://www.okx.com", "https://app.okx.com"]
    i4h = _request("POST", "/api/v5/aigc/mcp/indicators", body={
        "instId": "BTC-USDT", "timeframes": ["4H"],
        "indicators": {"RSI": {"paramList": [14]}, "SUPERTREND": {}},
    }, hosts=IND)[0]["data"][0]["timeframes"]["4H"]["indicators"]
    id1 = _request("POST", "/api/v5/aigc/mcp/indicators", body={
        "instId": "BTC-USDT", "timeframes": ["1Dutc"],
        "indicators": {"EMA": {"paramList": [20, 50, 200]}, "AHR999": {}},
    }, hosts=IND)[0]["data"][0]["timeframes"]["1Dutc"]["indicators"]

    st = i4h["SUPERTREND"][0]["values"]
    ema = id1["EMA"][0]["values"]
    ahr = id1["AHR999"][0]["values"]
    return {
        "rsi4h": float(i4h["RSI"][0]["values"]["14"]),
        "supertrend4h": {
            "value": float(st["superTrend"]),
            "direction": st.get("trend") or ("UP" if st.get("direction") == "1" else "DOWN"),
        },
        "ema_daily": {"ema20": float(ema["20"]), "ema50": float(ema["50"]), "ema200": float(ema["200"])},
        "ahr999": {"value": float(ahr["ahr999"]),
                   "dca_cost_200": float(ahr["dca_cost_200"]),
                   "fitted_price": float(ahr["fitted_price"])},
    }


def funding(inst="BTC-USDT-SWAP"):
    d = _request("GET", "/api/v5/public/funding-rate", {"instId": inst})[0]
    rate = float(d["fundingRate"])
    return {"rate_pct": rate * 100, "annual_pct": rate * 3 * 365 * 100,
            "funding_ts": int(d["fundingTime"])}


def open_interest():
    d = _request("GET", "/api/v5/public/open-interest",
                 {"instType": "SWAP", "instId": "BTC-USDT-SWAP"})[0]
    chg = None
    try:
        rows = [r for r in _request("GET", "/api/v5/rubik/stat/contracts/open-interest-volume",
                                    {"ccy": "BTC", "period": "1H"}) if r]
        if len(rows) >= 25:
            chg = (float(rows[0][1]) - float(rows[24][1])) / float(rows[24][1]) * 100
    except Exception:  # noqa: BLE001
        pass
    return {"oi_ct": float(d["oi"]), "oi_btc": float(d["oiCcy"]),
            "oi_usd": float(d.get("oiUsd") or 0), "oi_chg24h_pct": chg}


def snapshot():
    btc = ticker("BTC-USDT")
    px = btc["last"]
    ind = indicators()
    oi = open_interest()

    cross = {}
    for sym in ("NVDA-USDT-SWAP", "QQQ-USDT-SWAP", "XAU-USDT-SWAP", "CL-USDT-SWAP"):
        t = ticker(sym)
        cross[sym.split("-")[0]] = {"last": t["last"], "chg24h_pct": t["chg24h_pct"]}

    levels = [("4H SuperTrend", ind["supertrend4h"]["value"]),
              ("日线EMA20", ind["ema_daily"]["ema20"]),
              ("日线EMA50", ind["ema_daily"]["ema50"]),
              ("日线EMA200", ind["ema_daily"]["ema200"])]
    up = sorted([(v, n) for n, v in levels if v > px])
    dn = sorted([(v, n) for n, v in levels if v <= px], reverse=True)

    return {
        "time_cst": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
        "btc": btc,
        "oi": oi,
        "funding": funding(),
        **ind,
        "levels": {"resistance": {"name": up[0][1], "value": up[0][0]} if up else None,
                   "support": {"name": dn[0][1], "value": dn[0][0]} if dn else None},
        "cross": cross,
        "flat_market": abs(btc["chg24h_pct"]) < 1.0,
        "vol_alert": bool((oi["oi_chg24h_pct"] is not None and abs(oi["oi_chg24h_pct"]) >= 5)
                          or abs(btc["chg24h_pct"]) >= 3),
    }


if __name__ == "__main__":
    print(json.dumps(snapshot(), ensure_ascii=False, indent=1))
