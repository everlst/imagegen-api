---
name: imagegen-api
description: "通过用户配置的 OpenAI 兼容 Images API 生成或编辑高质量图片，支持独立的 Base URL、API Key、模型名称与分辨率。用于用户要求使用自定义图像接口、当前最新版 Image 模型、Flare 首次出图或 Sunburst 修图，以及沿用该接口的图像任务。已有 SVG、矢量图标或确定性代码图形的修改不使用此技能。"
---

# ImageGen API

使用本技能自己的 `scripts/image_gen.py` 和 `config.local.toml`。不依赖系统 imagegen 技能，也不修改它。

## 安装、更新与版本检查

安装和更新使用仓库的 `scripts/update_skill.py install`，不要用遇到已有目录就退出的下载流程代替。已有安装须更新原目录，不创建另一个同名技能。安装时读取仓库最新 README，下载最新更新脚本；默认路径会查找当前 Codex home 的 `skills/imagegen-api` 和 `~/.agents/skills/imagegen-api`，已知宿主加载路径时用 `--dest` 指定该目录。

`version.json` 是技能版本和当前模型的唯一来源。更新脚本检查固定 GitHub 仓库 `everlst/imagegen-api` 的 main 提交，更新托管文件，并将本地 `[models]` 同步到该版本。已有 API 地址、密钥、质量、尺寸及其他用户文件保留。更新前备份待修改文件，写入失败时恢复。

`image_gen.py` 在每次真实生成、编辑或批量任务前自动检查并应用更新，成功后重载当前脚本及配置。更新检查失败时停止，不使用旧版本继续出图。`check-config` 和 `--dry-run` 保持离线；它们展示本地版本，不宣称已检查远端。技能更新后重新读取当前 `SKILL.md`，避免继续使用会话中缓存的旧版说明。详细命令见 [references/configuration.md](references/configuration.md)。

## 安装后配置

处理安装后配置或首次配置任务时，读取 [references/configuration.md](references/configuration.md)，执行其中的“可选配置：全局图片默认方式”：先展示实际目标路径和待合并的规则，再由 Codex 询问是否添加到全局 `AGENTS.md`，得到明确同意后才写入。已存在等效规则时无需重复添加；跳过或尚未答复时不写入。本步骤由 Codex 对话执行，不由图片脚本自动修改全局文件；普通出图和修图任务不重复询问此选项。

## 默认行为

- 首次出图、重新创作、新的独立变体：使用随技能更新同步的 `models.generate`，当前为 `gpt-image-2.6-flare`。
- 修改已有图片、保留主体/身份/布局的局部调整：使用随技能更新同步的 `models.edit`，当前为 `gpt-image-2.6-sunburst`。
- 质量优先于速度；默认 `quality=max`。尺寸默认 `auto`，按任务用途或用户要求设置。用户明确指定的参数优先。
- 用户选择本技能处理图片请求时，使用已配置的 API，并遵循当前用户与宿主的授权要求。图像请求只发送到用户填写的服务地址；配置未完成时说明缺少的字段，不回退到其他服务或内置工具。

## 配置与运行

需要 Python 3.11+。遵循用户或项目指定的 Python 环境；没有约定时使用独立虚拟环境。依赖见 `requirements.txt`。下方 `python` 代表该环境的解释器，执行前从本技能所在路径定位脚本，不假定工作目录或安装目录。

默认配置位于本技能根目录的 `config.local.toml`，与当前工作目录无关。可通过 `--config /absolute/path/config.toml` 指定其他文件。连接信息显式传给 OpenAI SDK 的 `base_url` 和 `api_key`，不读取全局 `OPENAI_API_KEY` 或 `OPENAI_BASE_URL`。

安装脚本会在缺少配置时从 `config.example.toml` 创建 `config.local.toml`，已有配置则迁移模型字段；随后在本机填写连接信息。首次配置或连接问题时阅读 [references/configuration.md](references/configuration.md)。请用户在本机填写密钥，不要求在聊天中粘贴。检查配置时只运行 `check-config`，不展示配置文件全文。以下命令从技能根目录执行：

```bash
python scripts/image_gen.py check-config
```

该命令仅检查本地字段，显示地址、模型、默认参数和密钥是否存在，不联网、不验证服务可用性。普通出图请求直接调用脚本即可；真实请求会自动检查 GitHub 更新，无需另行执行 `check-config`。

## 执行流程

1. 判断是新创作还是修图，明确输出用途、尺寸、准确文字、保留内容和输入图角色。
2. 使用宿主可用的图像查看工具（例如 `view_image`）检查本地参考图或待修改图片。标明每张图片是参考、编辑对象还是合成素材。
3. 文本出图用 `generate`；修图用 `edit`。带参考图的新创作在 API 层也使用 `edit`，但须显式传入配置中的生成模型：`--model <models.generate>`。
4. 将提示词整理为主体、场景、风格、构图、光照、原样文字和约束。已有详细提示词只整理，不新增人物、物件、品牌或故事情节。
5. 多个不同文本出图任务可用 `generate-batch`，每个素材一个 JSONL 任务；带图的多任务分别调用 `edit`。`--n` 仅用于同一提示词的多个变体。
6. 查看实际输出，检查主体、文字、构图、细节、修改不变量，以及需要时的透明通道。具体缺陷用 Sunburst 定向修改，保留已接受的部分。
7. 将最终文件保存在用户指定位置或当前工作区。使用明确的 `--out` 或 `--out-dir`，沿用当前会话的输出目录规则；未经要求不覆盖原图。
8. 展示结果，报告实际请求的模型、质量、尺寸、提示词和保存路径。第三方服务的底层模型由该服务决定；以实际返回图片检查质量。

## 常用调用

首次出图，默认 Image 2.6 Flare + max：

```bash
python scripts/image_gen.py generate \
  --prompt "一只陶瓷杯的产品摄影，柔和侧光，无文字" \
  --size 2048x2048 --out /absolute/path/cup.png
```

修图，默认 Image 2.6 Sunburst + max：

```bash
python scripts/image_gen.py edit \
  --image /absolute/path/cup.png \
  --prompt "仅将背景改为浅灰色，杯子造型、纹理和位置保持不变" \
  --out /absolute/path/cup-v2.png
```

命令加 `--dry-run` 可检查最终请求参数，不联网，也不生成图片。具体参数见 `generate --help`、`edit --help` 或 `generate-batch --help`。

## 当前模型与参数

- 只使用 `version.json` 中的当前模型，更新时替换旧版模型配置，不保留旧模型选择或回退。`--model` 仅用于在当前 Flare / Sunburst 之间指定任务分工。质量可设置 `low / medium / high / xhigh / max / auto`；默认 `max`。
- 尺寸可设 `auto` 或 `宽x高`。脚本沿用现有尺寸校验：每边须是 16 的倍数，最长边 ≤3840，长宽比 ≤3:1，总像素 655,360～8,294,400。总像素超过 3,686,400（2560×1440）按实验性高分辨率使用，实际支持以所选模型接口为准。
- 透明输出使用 `--background transparent --output-format png` 或 `webp`。当前模型不额外传 `input_fidelity`。
- Image 2.6 的 `complexity` 与 `quality` 独立；本脚本不发送该字段，沿用官方默认 `high`。当前 CLI 输出格式为 PNG、JPEG、WebP；尚未接入 SVG、GIF 或 `markup` 参数。
- 自定义服务须提供 Images API 的生成与编辑端点，并支持当前模型 ID。服务不支持当前模型时报告错误，不自动退回旧型号。
- 发生认证、模型或参数不支持等错误时报告具体原因，不自动更换地址、模型或降低质量。

模型与参数依据（2026-11-13 核对）：[官方图像提示与迁移指南](https://developers.openai.com/api/docs/guides/image-prompting)、[图像生成指南](https://developers.openai.com/api/docs/guides/image-generation)。
