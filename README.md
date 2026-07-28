# XHS URL Video Capture

一个 macOS 专用的 Codex Skill：在用户手动登录的小红书网页会话中，采集单条帖子的可见页面信息、已渲染评论、可直接下载的视频及本地口播转写，并合并为一份 Markdown 报告。

不使用 OpenAI API、在线转写服务、私有 API，也不会读取或导出 Cookie、密码、验证码或本地存储。

## 功能

- 保留独立 Chrome 配置目录，登录一次后复用登录态。
- 提取标题、作者、正文、标签，以及页面显示的点赞、收藏、评论数量。
- 在有限时间内滚动评论区，并尝试展开已显示的回复。
- 仅对可直接获取的 MP4 使用本地 `faster-whisper` 生成口播稿。
- 输出一个 `post_and_transcript.md`，将帖子、评论和口播放在一起；页面或视频不可获取时，会在报告中说明原因。

## 系统要求

- macOS
- Python 3.9 或更高版本
- Google Chrome
- 可正常访问小红书的网络连接

首次安装需要下载 Python 依赖；第一次本地转写还会下载语音模型，请预留数分钟及足够磁盘空间。

## 安装

```bash
git clone <YOUR_REPOSITORY_URL>
cd xhs-url-video-capture
python3 scripts/setup.py
```

安装会在 `~/.xhs-url-video-capture/.venv` 创建独立运行环境，不污染系统 Python。

## 首次登录

```bash
zsh scripts/start_chrome.sh
```

在打开的专用 Chrome 窗口中手动登录小红书，并保持该窗口打开。登录状态保存在 `~/.xhs-url-video-capture/chrome-profile`，后续采集会复用它。

遇到验证码或登录失效时，请在该窗口中自行完成操作后重试；工具不会处理或导出任何登录凭据。

## 采集一条链接

```bash
~/.xhs-url-video-capture/.venv/bin/python scripts/run_capture.py \
  --url 'https://www.xiaohongshu.com/explore/<NOTE_ID>' \
  --output-dir ~/.xhs-url-video-capture/output \
  --max-video-seconds 600 \
  --max-video-mb 300
```

命令会打印报告路径，例如：

```text
~/.xhs-url-video-capture/output/20260728-120000/post_and_transcript.md
```

## 运行方式与限额

- 每次只采集一个链接；默认最多采集评论 90 秒、40 轮，连续 5 轮没有新增评论即停止。
- 默认跳过超过 600 秒或 300 MB 的视频，以节约本地计算与磁盘；帖子和评论仍会输出。
- 若想重试同一任务，可传入 `--run-dir <已有输出目录>`。已有报告会直接复用，已有视频或转写稿不会重复下载或转写。
- 如果 9222 端口被占用，请使用空闲端口启动专用 Chrome，并在采集命令中加入匹配的 `--cdp-url http://127.0.0.1:<PORT>`。

## 输出与限制

报告只包含登录态网页中实际渲染的内容。折叠、未加载、删除、受限或不可见的评论不会被补写。口播稿来自本地自动语音识别，不是人工校对的逐字稿；没有可下载 MP4 或转写失败时，报告会保留相应缺口说明。

## Codex 使用

将本目录作为 Skill 安装后，Codex 会读取 [SKILL.md](SKILL.md) 并使用相同的本地流程。面向 Codex 的精简操作说明见该文件。

## 许可

本项目采用 [MIT License](LICENSE)。使用时请遵守小红书的适用条款、当地法律以及内容作者的权利。
