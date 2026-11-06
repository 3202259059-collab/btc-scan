# BTC 消息面扫描 · 云端版

每 30 分钟（:00 / :30，Asia/Shanghai）拉 OKX 行情与四方向新闻，LLM 生成 ≤400 字报告，推到手机/IM/邮箱。
不依赖本机 DSH、不依赖 `okx` CLI，纯 Python 标准库。

## 组成

| 文件 | 作用 |
|---|---|
| `market.py` | OKX ticker / 持仓量 / 资金费率 / 4H RSI / 4H SuperTrend / 日线 EMA20-50-200 / AHR999 / 四个跨资产 |
| `news.py` | Google News RSS，四方向 × 中英 |
| `analyze.py` | 调 OpenAI 兼容接口（默认 DeepSeek）出报告；无 key 时退化为数据播报 |
| `notify.py` | Telegram / Bark / 飞书 / Server酱 / 邮件，配哪个发哪个 |
| `main.py` | 入口：单次 / `--dry-run` / `--loop`（每 30 分钟） |

指标走 OKX 公共指标接口 `/api/v5/aigc/mcp/indicators`，与本地 `okx` CLI 同源，数值一致
（AHR999 必须用 `1Dutc`，用 1H 会拿到 200 小时均价的错误口径）。

## 先本地验证

```bash
cp .env.example .env      # 填入 LLM_API_KEY 和至少一个推送渠道
python3 main.py --dry-run # 只打印，不推送
python3 main.py           # 真发一条
```

## 方案 A：VPS / 常开机器（推荐，真正云端）

```bash
# 装 docker 后
cd btc_scan/cloud
cp .env.example .env && vi .env
docker compose up -d --build
docker logs -f btc-scan    # 看每次执行
```

`--loop` 会自己对齐 :00/:30，不依赖宿主机 cron；容器 `restart: unless-stopped`，重启机器也会自动拉起。

## 方案 B：GitHub Actions（免服务器）

1. 把 `btc_scan/cloud/` 连同 `github-actions.yml` 推进一个仓库，workflow 放到 `.github/workflows/btc-scan.yml`。
2. 仓库 Settings → Secrets and variables → Actions，添加 `LLM_API_KEY` 和推送渠道的 secrets。
3. Actions 里手动 Run 一次验证。

注意：GitHub 的 cron 用 UTC，`*/30` 在任何时区都对齐 :00/:30；高峰期可能延迟几分钟；
仓库 60 天无提交会自动停用定时任务。

## 推送渠道

| 渠道 | 需要配置 | 说明 |
|---|---|---|
| Telegram | `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | 跨平台，最稳 |
| Bark | `BARK_URL` | iPhone 原生推送，免费 |
| 飞书 | `FEISHU_WEBHOOK` | 群机器人，国内快 |
| Server酱 | `SERVERCHAN_KEY` | 推到微信 |
| 邮件 | `SMTP_*` | QQ/163 需用授权码 |

多个渠道可同时开，失败互不影响；全都没配就只打印到控制台。

## 与本地 DSH 任务的关系

本地 `btc_scan/scan.py` + DSH 定时任务仍然可用（依赖本机开机）。云端跑通后建议把本地那条
`0,30 * * * *` 的 schedule 删掉，避免同一时间收到两份。
