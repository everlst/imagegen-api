# ImageGen API

通过独立配置的 OpenAI 兼容 Images API 生成和编辑图片的 Codex 技能。

- 首次出图默认使用 `gpt-image-2.6-flare`，修图默认使用 `gpt-image-2.6-sunburst`。
- 默认 `quality=max`、`size=auto`，支持按请求指定模型、质量、尺寸和输出格式。
- 支持参考图、蒙版编辑、JSONL 批量生成，以及 PNG、JPEG、WebP 输出。
- Base URL 和 API Key 保存在本机配置中，不读取全局 OpenAI 环境变量，也不自动切换服务或模型。

需要 Python 3.11+，以及可访问 Images API 的账号或兼容服务。实际生成与编辑使用配置服务的额度。

## 安装到 Codex

在 Codex 中发送：

```text
$skill-installer 从 https://github.com/everlst/imagegen-api/tree/main/skills/imagegen-api 安装这个技能。安装完成后，读取已安装技能的 SKILL.md 和 references/configuration.md，继续执行安装后配置，并询问我是否将其中的图片生成偏好添加到全局 AGENTS.md；我明确同意后再写入。
```

也可以克隆本仓库，把完整的 `skills/imagegen-api` 文件夹复制到 Codex 的技能目录。当前官方文档的用户级目录是 `~/.agents/skills/`，项目级目录是 `.agents/skills/`；内置安装器会选择其宿主使用的目录。安装后从 Codex 显示的技能路径定位文件，避免重复安装到多个目录。

Codex 会自动发现技能；未显示时重启 Codex。参考[官方技能安装说明](https://learn.chatgpt.com/docs/build-skills)。

### 可选：设为全局图片默认方式

使用上面的安装提示词时，Codex 会在安装后展示待添加的三条规则和全局 `AGENTS.md` 的实际路径，再询问是否添加。选择添加后，AI 出图与修图会默认使用 `imagegen-api`，包括网站配图和其他技能中的图片任务；已有 SVG、矢量图标、确定性代码图形的修改，以及绘图库数据图表不受此规则影响。

Codex 仅在明确同意后备份并合并规则，保留原有内容，避免重复添加。选择跳过或没有答复时不修改全局配置，仍可通过 `$imagegen-api` 使用技能。具体规则见[全局偏好配置](skills/imagegen-api/references/configuration.md#可选配置全局图片默认方式)。

手动复制技能，或先前只完成下载的用户，可在 Codex 中发送：

```text
$imagegen-api 请执行安装后配置，并询问我是否将图片生成偏好添加到全局 AGENTS.md。
```

## 配置

进入已安装的 `imagegen-api` 文件夹，使用现有项目环境，或创建独立的虚拟环境。以下为 macOS / Linux 示例：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp -n config.example.toml config.local.toml
chmod 600 config.local.toml
```

Windows 可使用 `python -m venv .venv` 创建环境，通过 `.venv\Scripts\Activate.ps1` 激活，并在文件管理器中复制配置模板。

用本机编辑器打开 `config.local.toml`，填写 `[api]` 的 `base_url` 和 `api_key`。OpenAI 官方地址为 `https://api.openai.com/v1`；使用兼容服务时填写该服务的 API 根地址及其密钥。

```bash
python scripts/image_gen.py check-config
```

此命令只检查本地字段，并显示密钥是否已配置，不联网。详细设置见[配置说明](skills/imagegen-api/references/configuration.md)。

## 使用

在 Codex 中直接提出图片任务：

```text
$imagegen-api 生成一张 2048×2048 的陶瓷杯产品照片，浅灰背景，柔和侧光，无文字。
```

```text
$imagegen-api 修改这张图片：仅将背景改成浅蓝色，保留杯子的造型、纹理和位置。
```

也可以从技能根目录使用命令行：

```bash
python scripts/image_gen.py generate \
  --prompt "一只陶瓷杯的产品摄影，柔和侧光，无文字" \
  --size 2048x2048 --out ./outputs/cup.png

python scripts/image_gen.py edit \
  --image ./outputs/cup.png \
  --prompt "仅将背景改为浅灰色，杯子造型、纹理和位置保持不变" \
  --out ./outputs/cup-v2.png
```

添加 `--dry-run` 可离线检查请求参数。配置文件默认相对于脚本定位，也可用 `--config /path/to/config.toml` 指定；无需在技能目录运行脚本。运行 `generate --help`、`edit --help` 或 `generate-batch --help` 查看参数。

## 模型与输出

支持 Image 2.6 / 2.5 的 Flare 与 Sunburst，以及配置中明确填写的服务商模型别名。`max`、透明背景和自定义尺寸的实际可用性取决于接口。新模型的 `complexity` 沿用官方默认 `high`；当前脚本没有接入 SVG、GIF 或 `markup` 参数。

仓库只提供空白配置模板。每位使用者应自行配置密钥；`config.local.toml`、虚拟环境和生成输出均不纳入版本管理。

模型参数参考[OpenAI 图像提示与迁移指南](https://developers.openai.com/api/docs/guides/image-prompting)。
