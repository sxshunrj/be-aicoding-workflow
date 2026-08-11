---
name: ai-workflow-init
description: Use when installing or diagnosing the ai-workflow Wave 1 Skill suite for Codex or Claude Code.
---

# AI Workflow Init

安装入口遵循固定顺序，Agent 负责 lifecycle，不把自更新责任塞给脚本。

## Sequence

`locate/update ai-workflow-init -> reread the latest SKILL.md -> run scripts/init.sh or scripts/init.ps1 -> inspect installed/updated/skipped/failed summary -> run doctor`

1. 定位当前 `ai-workflow-init` 来源；如用户要求更新，先更新 Skill 来源。
2. 重新读取最新 `SKILL.md`；Do not let init scripts update this Skill by themselves。
3. Unix/macOS 运行 `scripts/init.sh`；Windows PowerShell 运行 `scripts/init.ps1`。按需传入 `--client`、`--scope`、`--repo`、`--copy`、`--link`。
   默认安装模式是 auto：Windows 使用 copy，其他平台使用 link。
4. 检查 installer JSON 中的 installed/updated/skipped/failed summary；有 failed 就停止并报告。
5. 运行 `ai-workflow doctor --source-root ...`，确认 CLI、Skill discovery、repo config 与 Wiki lint。

不要写用户真实 skill 目录以外的文件；repo scope 必须带 `--repo`。安装脚本只做确定性安装与诊断，不运行 workflow phase。
