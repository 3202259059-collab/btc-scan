# btc-scan

每 30 分钟抓取 OKX 行情与四方向新闻，生成 400 字消息面报告，推送到 Bark。

- 代码在 `cloud/`
- 定时任务在 `.github/workflows/btc-scan.yml`
- 需要仓库 Secret：`BARK_URL`
