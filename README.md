# Fear & Greed Discord 每日播报

每天自动获取 **CNN 美股 Fear & Greed Index**，生成一张中文市场情绪卡片，并通过 Discord Webhook 推送。

## 当前效果

每次播报会自动生成一张 `1200 × 675` PNG，内容包括：

- 当前 Fear & Greed 分数和情绪区间
- 半圆情绪仪表盘
- 上一交易日、一周前、一个月前对比
- 近 30 个交易日情绪趋势
- 自动市场解读
- 简短 Discord 标题和图片附件

图片颜色会根据指数自动变化：恐慌为红色，贪婪为绿色。

## 自动运行

GitHub Actions 默认每天 `00:30 UTC` 执行，即 **北京时间 08:30**。

项目不需要服务器，也不需要 Discord Bot，只使用一个 Discord Webhook。

## 必须配置的 Secret

进入仓库：

`Settings → Secrets and variables → Actions → New repository secret`

创建：

```text
Name: DISCORD_WEBHOOK_URL
Secret: 你的 Discord Webhook 完整地址
```

不要把 Webhook URL 写进代码、README、Issue 或公开截图。

## 手动测试新版图片

进入：

`Actions → Daily Fear & Greed Broadcast → Run workflow`

- `dry_run: false`：生成图片并发送到 Discord
- `dry_run: true`：只生成图片，不发送

手动运行后，Actions 页面底部会出现 `fear-greed-card-preview`，可以下载查看本次生成的 PNG。预览文件保留 3 天。

## 本地运行

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
DRY_RUN=true python src/fear_greed_bot.py
```

Linux 环境需要安装支持中文的字体，例如 `fonts-noto-cjk`。GitHub Actions 已经自动安装。

## 修改播报时间

编辑 `.github/workflows/daily-fear-greed.yml` 中的 cron。GitHub Actions cron 使用 UTC。

```yaml
# 北京时间 08:30
- cron: "30 0 * * *"

# 北京时间 09:00
- cron: "0 1 * * *"
```

## 可选环境变量

- `BROADCAST_TITLE`：Discord 消息标题
- `WEBHOOK_USERNAME`：Discord 显示名称
- `DISCORD_ROLE_MENTION`：提醒指定角色，例如 `<@&123456789012345678>`
- `OUTPUT_IMAGE_PATH`：生成图片的保存路径
- `FONT_REGULAR`：自定义常规字体路径
- `FONT_BOLD`：自定义粗体字体路径
- `FNG_API_URL`：自定义数据接口

## 数据说明

数据来自 CNN Fear & Greed Index 的公开数据接口。本工具仅用于市场情绪展示，不构成投资建议。
