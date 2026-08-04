# XHS URL Video Capture

一个 macOS 专用的 Codex Skill：只通过小红书公开 HTML 将单条视频或图文笔记转换为可复用的本地内容包。

不使用浏览器自动化、Chrome、Cookie、登录、JavaScript 执行、私有 API 或签名生成；也不采集评论正文或二级回复。

## 功能

- 普通 HTTP 跟随公开短链跳转，并解析公开 HTML 中的初始化数据。
- 提取标题、作者、正文、标签和公开互动数快照。
- 下载当前笔记对象中直接给出的 MP4 候选及封面图片候选。
- 对已下载视频使用本地 `faster-whisper` 生成口播稿。
- 保存 `content_package.json`、`report.md`、HTML、初始化数据、媒体候选、视频/封面或有序图片；视频还可输出本地时间戳口播和 SRT 字幕。

## 安装

```bash
git clone <YOUR_REPOSITORY_URL>
cd xhs-url-video-capture
python3 scripts/setup.py
```

安装会在 `~/.xhs-url-video-capture/.venv` 创建独立运行环境。首次转写会下载语音模型。

## 采集一条链接

```bash
~/.xhs-url-video-capture/.venv/bin/python scripts/run_capture.py \
  --url 'https://www.xiaohongshu.com/explore/<NOTE_ID>' \
  --output-dir ~/.xhs-url-video-capture/output \
  --max-video-mb 300
```

## 边界与限制

- 每次只采集一条链接；遇到登录、验证、限流、私密内容、无公开数据或无直接媒体候选即停止。
- 对可直接识别笔记 ID 的链接，若输出目录已有同一内容包，会复用已有结果，避免重复下载媒体。
- 封面只使用当前笔记数据内已有的完整公开图片 URL；不会根据资源 ID 猜测地址或补签名。
- 不采集评论正文、二级回复、未加载内容或推荐内容。
- 本地自动转写不是人工校对稿；视频或封面未能直接下载时，报告会明确写出限制。
- 请遵守小红书适用条款、当地法律及内容作者权利。
