# ImageGen API

通过独立配置的 OpenAI 兼容 Images API 生成和编辑图片的 Codex 技能。

- 模型跟随技能最新发布版本；当前首次出图使用 `gpt-image-2.6-flare`，修图使用 `gpt-image-2.6-sunburst`。
- 安装时检测并更新已有版本，每次实际出图前自动检查 GitHub 更新，同时迁移本地模型配置。
- 默认 `quality=max`、`size=auto`，支持按请求指定模型、质量、尺寸和输出格式。
- 支持参考图、蒙版编辑、JSONL 批量生成，以及 PNG、JPEG、WebP 输出。
- Base URL 和 API Key 保存在本机配置中，不读取全局 OpenAI 环境变量；调用失败时不切换服务或回退到旧模型。

需要 Python 3.11+，以及可访问 Images API 的账号或兼容服务。实际生成与编辑使用配置服务的额度。

## 安装或更新到 Codex

在 Codex 中发送：

```text
请从 https://github.com/everlst/imagegen-api 安装或更新 imagegen-api。先读取仓库最新 README，下载并运行 skills/imagegen-api/scripts/update_skill.py 的 install 命令。已有技能时更新原目录，保留 API 地址、密钥和输出参数，将模型配置同步到仓库最新版，并默认启用出图前自动更新。完成后读取更新后的 SKILL.md 和 references/configuration.md，运行 check-config 核对技能版本和实际模型，再询问我是否将图片生成偏好添加到全局 AGENTS.md；明确同意后再写入。
```

这条指令同时适用于首次安装和已安装旧版的电脑。安装器会复用当前 Codex home 的 `skills/imagegen-api` 或 `~/.agents/skills/imagegen-api` 中的已有安装。自定义目录、项目级安装或多个副本时，使用 `--dest` 指向 Codex 实际加载的技能目录。

也可下载本仓库，在仓库根目录执行（Python 3.11+）：

```bash
python skills/imagegen-api/scripts/update_skill.py install
```

更新脚本只依赖 Python 标准库，会从 GitHub 下载最新提交；不会因安装目录已存在而跳过。旧版本没有更新脚本时，先下载最新仓库或由 Codex 执行上方安装指令，不能继续运行旧版安装语句。

Codex 会自动发现技能；未显示时重启 Codex。参考[官方技能安装说明](https://learn.chatgpt.com/docs/build-skills)。

### 可选：设为全局图片默认方式

使用上面的安装提示词时，Codex 会在安装后展示待添加的三条规则和全局 `AGENTS.md` 的实际路径，再询问是否添加。选择添加后，AI 出图与修图会默认使用 `imagegen-api`，包括网站配图和其他技能中的图片任务；已有 SVG、矢量图标、确定性代码图形的修改，以及绘图库数据图表不受此规则影响。

Codex 仅在明确同意后备份并合并规则，保留原有内容，避免重复添加。选择跳过或没有答复时不修改全局配置，仍可通过 `$imagegen-api` 使用技能。具体规则见[全局偏好配置](skills/imagegen-api/references/configuration.md#可选配置全局图片默认方式)。

## 配置

进入已安装的 `imagegen-api` 文件夹，使用现有项目环境，或创建独立的虚拟环境。以下为 macOS / Linux 示例：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
chmod 600 config.local.toml
```

Windows 可使用 `python -m venv .venv` 创建环境，通过 `.venv\Scripts\Activate.ps1` 激活。安装脚本已在缺少配置时创建空白 `config.local.toml`。

用本机编辑器打开 `config.local.toml`，填写 `[api]` 的 `base_url` 和 `api_key`。OpenAI 官方地址为 `https://api.openai.com/v1`；使用兼容服务时填写该服务的 API 根地址及其密钥。

```bash
python scripts/image_gen.py check-config
```

此命令只检查本地字段，并显示密钥是否已配置，不联网。详细设置见[配置说明](skills/imagegen-api/references/configuration.md)。

## 自动更新

当前技能版本由 [version.json](skills/imagegen-api/version.json) 管理。每次真实生成、编辑或批量任务开始前，脚本检查本仓库 main 的最新提交；有更新时先备份、更新技能和本地模型配置，再执行图片请求。`check-config` 和 `--dry-run` 保持离线。主动更新可从已安装技能目录执行：

```bash
python scripts/update_skill.py update
python scripts/image_gen.py check-config
```

更新保留 API 地址、密钥、质量、尺寸、虚拟环境和用户文件，仅将模型字段同步为仓库当前版本。更新检查失败会停止，不继续调用旧型号。模型升级由仓库版本发布控制，当前为 Image 2.6；不维护旧模型选项或自动回退。备份位于安装目录旁的 `.imagegen-api-backups/`，只保留在本机。

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

只使用当前发布版本的 Flare 与 Sunburst，`--model` 可在这两个当前型号之间选择。自定义接口需支持这些型号及相应参数。`complexity` 沿用官方默认 `high`；当前脚本没有接入 SVG、GIF 或 `markup` 参数。

仓库只提供空白配置模板。每位使用者应自行配置密钥；`config.local.toml`、虚拟环境和生成输出均不纳入版本管理。

模型参数参考[OpenAI 图像提示与迁移指南](https://developers.openai.com/api/docs/guides/image-prompting)。
