# AI Workflow

Status: wave-1 trial; wave-2 local conformance in progress

本仓库提供一套 Skill-first 的本地 AI coding workflow：`spec -> plan -> implement -> verify` 持久化流程、schema-v2 ChildResult、LLM Wiki 检索/反思/治理、以及 Codex/Claude Code 可发现的 Wave 1 Skill 套件。Python Helper Core 只做确定性校验和状态持久化；语义判断仍由 Agent 与人类 gate 负责。

## 本地准备

1. 安装 Python 3.11+。
2. 安装依赖：`pip install -e '.[dev]'`。
3. 安装 Skill：`bash skills/ai-workflow-init/scripts/init.sh --client all --scope user`。
4. 诊断环境：`ai-workflow doctor --source-root "$PWD/skills" --repo "$PWD/examples/language-neutral" --client all`。
5. 运行离线验证：`python -m pytest -q`。

## Wave 1 Skills

- `$ai-workflow-init`：安装和诊断 Skill 套件。
- `$ai-workflow-harness`：持久化四阶段 workflow。
- `$ai-small-tdd-change`：显式触发的小范围 TDD。
- `$ai-git-handoff`：人工选择后的 Git 收尾。
- `$ai-knowledge-reflection`：终态 run 到候选知识的证据化反思。
- `$ai-knowledge-governance`：候选知识 review/promote/reject gate。

## Wave 2 Skills

- `$ai-workflow-harness-grill`：交互式 PRD 驱动的 `plan -> implement -> verify` workflow。
- `$ai-integration-test-checklists`：生成 evidence-mapped integration-test checklist。
- `$ai-integration-test-generator`：基于 repository adapter 生成或更新集成测试资产。
- `$ai-integration-test-v2`：执行、诊断和收敛 integration tests。
- `$ai-ci-failure-triage`：收集 CI failed-job facts 并路由失败。

## Example

`examples/language-neutral` 是离线接入样例。它使用 schema v2 配置 `build` 与 `unit_test` 命令，禁用 `verify.integration_test`，并把 Wiki 指向 sibling `../../wiki`。

真实 Codex trial 请按 [docs/wave-1-trial.md](docs/wave-1-trial.md) 执行，并把 evidence template 填回。当前 traceability 只记录本地离线证据；未声明 Codex 或 Claude Code 已完成真实客户端验收。

Wave 2 真实客户端 trial 请按 [docs/wave-2-trial.md](docs/wave-2-trial.md) 执行；未回填 evidence 前，不声明 `reference-parity`。
