# 配置 OpenAI 兼容图像服务

配置文件位于本技能根目录的 `config.local.toml`。脚本根据自身路径定位配置，与当前工作目录无关。

## 首次配置

1. 选择 Python 3.11+ 环境，遵循用户或项目已有的环境约定。依赖通过该解释器安装：`python -m pip install -r requirements.txt`。
2. 将技能根目录的 `config.example.toml` 复制为 `config.local.toml`，已有配置时保留原文件。
3. 请用户在本机编辑器填写服务地址和密钥，不要求在聊天中粘贴密钥。在 macOS / Linux 上执行 `chmod 600 config.local.toml`，限制为当前用户可读写。

配置结构如下；空字符串需要用户填写：

```toml
[api]
base_url = ""
api_key = ""

[models]
generate = "gpt-image-2.6-flare"
edit = "gpt-image-2.6-sunburst"

[defaults]
quality = "max"
size = "auto"
output_format = "png"
```

`base_url` 填 API 根地址。OpenAI 官方地址为 `https://api.openai.com/v1`；兼容服务可能使用 `/v1`、`/openai/v1` 或其他路径，按其文档填写。脚本会追加 `images/generations` 或 `images/edits`，不要填完整端点或网站聊天页面。

`api_key` 填该服务颁发的密钥。不要把实际密钥放入聊天、命令行参数、技能正文或分享包。`config.local.toml` 已被 `.gitignore` 忽略。

`generate` 和 `edit` 是发送给服务商的模型 ID。不同服务的别名可直接在此填写。单次请求可用 `--model`、`--quality`、`--size`、`--output-format` 覆盖配置。Image 2.6 的 `complexity` 不写入当前配置，脚本省略该字段，沿用官方默认 `high`。

## 检查配置

以下命令从技能根目录执行，`python` 代表已选择环境的解释器：

```bash
python scripts/image_gen.py check-config
```

成功时显示 `api_key_set: true`、地址、模型和默认参数，退出码为 0。该命令不联网，也不显示密钥；缺少地址或密钥时以非零状态退出。

离线检查一次图片请求：

```bash
python scripts/image_gen.py generate \
  --prompt "一只陶瓷杯的产品摄影，浅灰背景，无文字" \
  --size 2048x2048 --out ./outputs/cup.png --dry-run
```

实际出图时去掉 `--dry-run`。从其他目录运行时使用脚本的真实路径；可用 `--config /absolute/path/another.toml` 指定另一份配置。

## 服务接口要求

- 文本出图：`POST <base_url>/images/generations`，JSON 请求。
- 编辑或参考图输入：`POST <base_url>/images/edits`，multipart 请求。
- 鉴权：`Authorization: Bearer <api_key>`。
- 返回标准 Images API 的 `data[].b64_json` 或 `data[].url`。脚本保存 Base64 图片，或下载返回的图片 URL；下载图片时不附带 API 密钥。
- 仅提供 `/chat/completions` 的服务不足以支持本技能。
- 遇到认证、模型或参数错误时报告具体原因，不自动更换服务、模型或降低质量。

脚本显式传入配置的地址和密钥，不读取全局 `OPENAI_API_KEY`、`OPENAI_BASE_URL`。缺少配置时不会自动转到官方 API。

## 依据

Image 2.6 型号、质量和默认 complexity 依据[官方图像提示与迁移指南](https://developers.openai.com/api/docs/guides/image-prompting)；尺寸校验沿用[官方图像生成指南](https://developers.openai.com/api/docs/guides/image-generation)中的既有范围（2026-11-13 核对）。兼容服务以其实际支持为准。
