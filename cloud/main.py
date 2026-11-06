#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BTC 消息面扫描 · 云端入口

用法：
  python3 main.py             # 跑一次
  python3 main.py --dry-run   # 跑一次但不推送
  python3 main.py --loop      # 常驻，每 30 分钟（:00 / :30）执行
"""
import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone

import analyze
import market
import news
import notify

CST = timezone(timedelta(hours=8))
HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "history.jsonl")


def _load_env(name):
    """读取同目录的 .env / config.env，已存在的环境变量优先"""
    path = os.path.join(HERE, name)
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


for _f in ("config.env", ".env"):
    _load_env(_f)


def run_once(dry=False):
    t0 = time.time()
    snap = market.snapshot()
    items = news.fetch()
    report = analyze.build(snap, items)
    print(report)
    with open(HIST, "a", encoding="utf-8") as f:
        f.write(json.dumps({"time": snap["time_cst"], "price": snap["btc"]["last"],
                            "report": report}, ensure_ascii=False) + "\n")
    if not dry:
        for name, ok, detail in notify.send(report):
            print(f"[notify] {name}: {'ok' if ok else 'FAIL ' + detail}", file=sys.stderr)
    print(f"[done] {time.time() - t0:.1f}s", file=sys.stderr)
    return report


def next_slot(now=None):
    now = now or datetime.now(CST)
    nxt = now.replace(minute=0 if now.minute < 30 else 30, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(minutes=30)
    return nxt


def loop():
    print(f"[loop] start at {datetime.now(CST):%F %T}", file=sys.stderr)
    while True:
        nxt = next_slot()
        wait = (nxt - datetime.now(CST)).total_seconds()
        print(f"[loop] next run {nxt:%m-%d %H:%M}", file=sys.stderr)
        time.sleep(max(1, wait))
        try:
            run_once()
        except Exception:  # noqa: BLE001
            err = traceback.format_exc()
            print(err, file=sys.stderr)
            try:
                notify.send("扫描异常：\n" + err[-300:], "BTC 扫描失败")
            except Exception:  # noqa: BLE001
                pass
        time.sleep(1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--loop", action="store_true")
    args = ap.parse_args()
    if args.loop:
        loop()
    else:
        run_once(dry=args.dry_run)
