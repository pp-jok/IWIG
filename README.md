# XHS Public Content Package Capture

将一条公开小红书视频或图文笔记转换为可追溯、可复用的本地内容包，供 Codex 后续拆解、对比、归档或内容理解使用。

只读取公开 HTML：不使用浏览器自动化、Cookie、登录、JavaScript 执行、私有接口、签名、代理或评论接口。

## 能力

- 规范化原始链接、跳转后链接与笔记 ID；直接链接支持按 ID 复用已有内容包，`--force` 可生成新快照。
- 提取标题、正文、标签、作者公开信息、发布时间与公开互动数据。
- 视频笔记：视频、封面、文件哈希、时长、分辨率、编码、本地转写、时间戳分段、SRT。
- 图文笔记：公开暴露的全部图片按原始顺序保存，并记录 PNG、JPEG、WebP 的尺寸、格式与哈希。
- 可选本地视觉处理：关键帧、macOS Vision OCR、封面/图文页/关键帧文字。
- 保存公开 HTML、初始化数据、候选地址、实际使用媒体地址、完整度与限制说明。
- 允许补处理已有内容包，不需要再次请求小红书或下载媒体。

## 安装

```bash
git clone https://github.com/pp-jok/xhs-url-video-capture.git
cd xhs-url-video-capture
python3 scripts/setup.py
```

运行环境位于 `~/.xhs-url-video-capture/.venv`。首次使用本地转写会下载语音模型。

## 采集

```bash
~/.xhs-url-video-capture/.venv/bin/python scripts/run_capture.py \
  --url 'https://www.xiaohongshu.com/explore/<NOTE_ID>' \
  --output-dir ~/.xhs-url-video-capture/output \
  --max-video-mb 300 \
  --keyframes --ocr
```

`--keyframes` 抽取候选画面并选择结构关键帧；`--ocr` 使用本地 macOS Vision 识别封面、图文页与关键帧文字。两者均可省略，且不会上传媒体。

对已有包补做关键帧和 OCR：

```bash
~/.xhs-url-video-capture/.venv/bin/python scripts/run_capture.py \
  --enrich-dir ~/.xhs-url-video-capture/output/<RUN_ID> \
  --keyframes --ocr
```

## 输出结构

```text
<RUN_ID>/
  content_package.json       # 供其他 Skill 使用的结构化接口
  report.md                  # 人读摘要、完整度与限制
  source/                    # HTML、初始化数据、媒体候选
  media/                     # 视频、封面或有序图文页
  derived/                   # 转写、SRT、关键帧
```

`content_package.json` 会区分 `available`、`zero`、`not_exposed`、`failed`、`not_run` 与 `intentionally_not_collected`，避免把缺失数据误判为零。

## 限制

- 每次仅处理一条用户提供的公开链接；遇到登录、验证、限流或无法访问即停止。
- 不采集评论正文、二级回复、作者主页深度信息、未加载或推荐内容。
- 只使用页面当前直接暴露的完整媒体 URL，不猜测地址、不补签名。
- 本地转写与 OCR 均可能存在识别误差；OCR 仅支持 macOS Vision，首次调用可能需要编译 Swift 工具。
- 请遵守平台条款、适用法律与创作者权利。
