#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多通道推送：Telegram / Bark / 飞书 / Server酱 / 邮件

按环境变量自动启用，配了哪个发哪个；一个都没配就只打印。
"""
import json
import os
import smtplib
import ssl
import urllib.parse
import urllib.request
from email.header import Header
from email.mime.text import MIMEText


def _post(url, payload, headers=None):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode()[:200]


def send_telegram(text):
    token, chat = os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"]
    return _post(f"https://api.telegram.org/bot{token}/sendMessage",
                 {"chat_id": chat, "text": text, "disable_web_page_preview": True})


def send_bark(text, title="BTC 消息面扫描"):
    """POST /push，避免长文本塞进 URL 路径触发长度限制"""
    url = os.environ["BARK_URL"].rstrip("/")
    base, _, key = url.rpartition("/")
    return _post(f"{base}/push", {"device_key": key, "title": title,
                                  "body": text, "group": "btc-scan"})


def send_feishu(text, title="BTC 消息面扫描"):
    return _post(os.environ["FEISHU_WEBHOOK"], {"msg_type": "text",
                                                "content": {"text": f"{title}\n{text}"}})


def send_serverchan(text, title="BTC 消息面扫描"):
    key = os.environ["SERVERCHAN_KEY"]
    data = urllib.parse.urlencode({"title": title, "desp": text}).encode()
    req = urllib.request.Request(f"https://sctapi.ftqq.com/{key}.send", data=data,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read().decode()[:200]


def send_email(text, title="BTC 消息面扫描"):
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "465"))
    user, pwd = os.environ["SMTP_USER"], os.environ["SMTP_PASS"]
    to = os.environ.get("MAIL_TO", user)
    msg = MIMEText(text, "plain", "utf-8")
    msg["Subject"] = Header(title, "utf-8")
    msg["From"], msg["To"] = user, to
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(host, port, context=ctx, timeout=20) as s:
        s.login(user, pwd)
        s.sendmail(user, [to], msg.as_string())
    return "ok"


CHANNELS = [
    ("telegram", ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"], send_telegram),
    ("bark", ["BARK_URL"], send_bark),
    ("feishu", ["FEISHU_WEBHOOK"], send_feishu),
    ("serverchan", ["SERVERCHAN_KEY"], send_serverchan),
    ("email", ["SMTP_HOST", "SMTP_USER", "SMTP_PASS"], send_email),
]


def enabled():
    return [name for name, keys, _ in CHANNELS if all(os.environ.get(k) for k in keys)]


def send(text, title="BTC 消息面扫描"):
    """返回 [(channel, ok, detail)]"""
    results = []
    for name, keys, fn in CHANNELS:
        if not all(os.environ.get(k) for k in keys):
            continue
        try:
            fn(text) if name != "email" else fn(text, title)
            results.append((name, True, ""))
        except Exception as e:  # noqa: BLE001
            results.append((name, False, str(e)[:120]))
    if not results:
        print("[notify] 未配置任何推送通道，仅输出到控制台")
    return results
