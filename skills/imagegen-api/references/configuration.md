# 配置 OpenAI 兼容图像服务

配置文件位于本技能根目录的 `config.local.toml`。脚本根据自身路径定位配置，与当前工作目录无关。

## 首次配置

1. 选择 Python 3.11+ 环境，遵循用户或项目已有的环境约定。依赖通过该解释器安装：`python -m pip install -r requirements.txt`。
2. 先运行安装/更新入口。没有配置时会创建 `config.local.toml`；已有配置时保留接口、密钥和其他参数，并自动迁移模型字段。
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

`generate` 和 `edit` 由 `version.json` 定义，并在安装和更新时同步到本地配置。模型跟随仓库最新发布版本，不继续使用旧型号。单次请求可用 `--model` 在当前 Flare / Sunburst 之间选择，并用 `--quality`、`--size`、`--output-format` 覆盖输出参数。Image 2.6 的 `complexity` 不写入当前配置，脚本省略该字段，沿用官方默认 `high`。

## 安装和自动更新

安装或重新安装时，下载仓库最新的 `skills/imagegen-api/scripts/update_skill.py`，使用已选择的 Python 3.11+ 解释器执行：

```bash
python /path/to/downloaded/update_skill.py install
```

默认复用检测到的已有安装；自定义或项目级安装须传 `--dest /absolute/path/to/imagegen-api`，该路径是技能本身的目录。如果发现多个同名安装，选择宿主实际加载的目录，避免更新了另一个副本。首次安装使用当前 Codex home 下的 `skills/imagegen-api`。

已安装新版时可主动检查并更新：

```bash
python scripts/update_skill.py update
```

更新检查和自动更新默认启用：每次真实生成、编辑或批量任务前检查 `everlst/imagegen-api` 的 main 提交，更新后重载再发起图片请求。同一批量任务只在开始时检查；`check-config`、帮助和 `--dry-run` 不联网。更新接口不会收到图片服务的 API 密钥。

升级同时覆盖托管的技能文件，并把 `[models]` 迁移到 `version.json` 中的型号。`[api]`、`[defaults]`、文件权限、虚拟环境和用户文件保留。备份保存在安装目录旁的 `.imagegen-api-backups/` 私有 ZIP 文件中，可能包含旧配置密钥，只保留在本机。失败时停止并说明原因，不静默使用旧版本或旧型号。`--config` 指定的独立配置也会在该次真实调用前迁移模型字段。

安装或更新完成后必须执行 `check-config`，核对实际安装路径、`skill_version`、`automatic_updates` 和两个模型；不能只凭“目录已存在”或 SKILL.md 中的版本文字宣称完成。接口尚未填写时说明缺少字段，继续执行可选全局偏好询问。已有配置时，用一次 `generate --dry-run` 确认最终请求的型号；此步骤不生成图片。

## 检查配置

以下命令从技能根目录执行，`python` 代表已选择环境的解释器：

```bash
python scripts/image_gen.py check-config
```

成功时显示 `skill_version`、`automatic_updates: true`、`api_key_set: true`、地址、模型和默认参数，退出码为 0。该命令不联网，也不显示密钥；缺少地址或密钥时以非零状态退出。

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

## 可选配置：全局图片默认方式

安装后配置和首次配置任务中，由 Codex 询问是否启用此选项。此选项写入全局 `AGENTS.md`，不增加 `config.local.toml` 的字段。用户只安装技能或要求生成图片，不代表同意修改全局偏好；普通图片任务不触发本步骤。

1. 定位当前 Codex home 下的 `AGENTS.md`：设置了 `CODEX_HOME` 时使用该目录，否则使用 `~/.codex/AGENTS.md`。不要从技能安装目录推断全局配置位置，也不要改写环境变量。
2. 只读检查目标文件，准备保留原有内容的最小合并方案。三条规则已有等效内容时跳过写入并告知；只有部分存在时仅准备补齐缺失内容。若与已有图片工具偏好冲突，将拟替换的具体规则一并展示，不自行删除冲突内容。
3. 展示实际目标路径和下方待添加规则，并询问：“是否将这三条图片生成偏好添加到全局 AGENTS.md，让各项目的 AI 出图和修图默认使用 imagegen-api？”提供“添加”和“跳过”选项。只有用户明确同意展示的变更后才写入；拒绝、未答复或超时均不写入，也不妨碍完成技能安装和接口配置。已有针对本次具体变更的明确同意时不重复确认。
4. 获得同意后，修改已有文件前先在本机保存备份，并遵循用户已有的备份或版本管理约定。将缺失规则合并到现有“基本偏好”部分；没有合适位置时追加该部分；文件不存在时按下方结构创建。保留无关内容、已有标题、格式和文件权限，不把个人全局配置或备份提交到本技能仓库。
5. 写入后检查差异：只包含已同意的规则，无重复条目、无无关改动。报告实际路径及备份位置；提示在新会话中读取更新后的全局规则。选择跳过后，不在后续普通出图任务中再次询问。

若 Codex home 下存在非空 `AGENTS.override.md`，它会优先于 `AGENTS.md` 被读取。展示合并方案时说明这一现状；仅写入 `AGENTS.md` 可能暂不生效，不自动修改、删除或重命名 override 文件。全局规则的读取顺序见[官方 AGENTS.md 说明](https://learn.chatgpt.com/docs/agent-configuration/agents-md)。

待添加的规则如下；标题仅在缺失时创建，三条规则保持原意和文本：

```markdown
# 全局工作约定

## 基本偏好

- 涉及 AI 图片生成或编辑时，默认使用 `imagegen-api` 技能，包括网站配图及其他技能流程中的出图、修图步骤。除非我明确指定其他方式，否则不使用内置 `image_gen` 工具或其他图片服务。
- 执行前读取并遵循 `imagegen-api` 的 `SKILL.md`，接口、模型和默认参数沿用该技能的本地配置。技能不可用、配置缺失或调用失败时，说明具体原因，不自动切换工具、服务或模型。
- 已有 SVG、矢量图标和确定性代码图形的修改，以及使用绘图库生成数据图表，不适用上述图片生成规则。
```

## 依据

Image 2.6 型号、质量和默认 complexity 依据[官方图像提示与迁移指南](https://developers.openai.com/api/docs/guides/image-prompting)；尺寸校验沿用[官方图像生成指南](https://developers.openai.com/api/docs/guides/image-generation)中的既有范围（2026-11-13 核对）。兼容服务以其实际支持为准。
