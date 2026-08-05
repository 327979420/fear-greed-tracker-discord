# Fear & Greed Discord 每日播报

每天自动获取 **CNN 美股 Fear & Greed Index**，生成中文 Discord Embed，并通过 Discord Webhook 推送。

## 已实现

- 当前 Fear & Greed 分数与中文情绪区间
- 上一交易日、一周前、一个月前对比
- 自动生成简短市场情绪解读
- Discord 彩色 Embed
- GitHub Actions 每日定时运行
- 手动测试与 Dry Run
- 网络重试、错误日志和单元测试
- 不需要服务器，也不需要创建 Discord Bot

## 默认时间

GitHub Actions 默认每天 `00:30 UTC` 执行，即 **北京时间 08:30**。

## 唯一必须配置的 Secret

在目标 GitHub 仓库中进入：

`Settings → Secrets and variables → Actions → New repository secret`

创建：

```text
Name: DISCORD_WEBHOOK_URL
Secret: 你的 Discord Webhook 完整地址
```

不要把 Webhook URL 写进代码、README、Issue 或聊天截图。

## 创建 Discord Webhook

1. 打开需要接收播报的 Discord 频道。
2. 点击频道设置。
3. 进入 `Integrations → Webhooks`。
4. 点击 `New Webhook`。
5. 选择频道并复制 Webhook URL。
6. 将它保存为 GitHub Secret `DISCORD_WEBHOOK_URL`。

## 第一次测试

进入 GitHub 仓库：

`Actions → Daily Fear & Greed Broadcast → Run workflow`

- 先把 `dry_run` 设为 `true`，确认数据抓取和消息结构正常。
- 再设为 `false`，确认 Discord 收到消息。

## 本地测试

本项目只使用 Python 标准库，无需安装依赖。

```bash
python -m unittest discover -s tests -v
DRY_RUN=true python src/fear_greed_bot.py
```

## 修改播报时间

编辑 `.github/workflows/daily-fear-greed.yml` 中的 cron。GitHub Actions cron 使用 UTC。

常用示例：

```yaml
# 北京时间 08:30
- cron: "30 0 * * *"

# 北京时间 09:00
- cron: "0 1 * * *"

# 墨尔本时间不适合用固定 UTC 全年表达，因为存在夏令时切换。
```

## 可选设置

工作流中的环境变量可以修改：

- `BROADCAST_TITLE`：卡片标题
- `WEBHOOK_USERNAME`：Discord 显示名称
- `DISCORD_ROLE_MENTION`：需要提醒的角色，例如 `<@&123456789012345678>`
- `FNG_API_URL`：自定义数据接口

## 数据说明

数据来自 CNN Fear & Greed Index 的公开数据接口。本工具仅用于市场情绪展示，不构成投资建议。
