# Wave 1 Real-Client Trial

本指南用于真实 Codex trial。先完成本地安装和诊断，再在 Codex 中显式调用各 Skill。不要把本地离线测试当成真实客户端验收。

## 1. Install

```bash
pip install -e '.[dev]'
bash skills/ai-workflow-init/scripts/init.sh --client all --scope user
ai-workflow doctor --source-root "$PWD/skills" --repo "$PWD/examples/language-neutral" --client all
```

在 Codex 中运行 `/skills`，确认能看到：

```text
ai-workflow-init
ai-workflow-harness
ai-small-tdd-change
ai-git-handoff
ai-knowledge-reflection
ai-knowledge-governance
```

## 2. Small TDD Trial

Prompt:

```text
使用 $ai-small-tdd-change。请对 examples/language-neutral 做一个小改动：让 verify.sh 对未知命令输出 usage，并先写失败测试。
```

期望：Agent 先澄清，给出 RED/GREEN evidence，独立验证，不提交 Git。

## 3. Four-Phase Harness Trial

Prompt:

```text
使用 $ai-workflow-harness，在 examples/language-neutral 上启动一个完整四阶段 run。需求：验证 Wave 1 language-neutral workflow 能完成 spec、plan、implement、verify，并记录知识反思候选。
```

期望：Harness 按 `status -> begin -> dispatch -> stage -> barrier -> finalize -> review -> transition -> status` 推进，所有 ChildResult 都来自 child，不直接编辑 `.ai-workflow/runs/**`。

## 4. New-Conversation Recovery

开启新 Codex 会话后输入：

```text
使用 $ai-workflow-harness。请从 repo 的 ai-workflow status 恢复上一个 run，不要根据聊天记录重建状态。
```

期望：Agent 先运行 `workflow status`，从持久化状态继续。

## 5. Reflection And Governance

终态 run 被人类接受后：

```text
使用 $ai-knowledge-reflection，为 RUN_ID 生成 evidence-backed reflection；如有可复用知识，创建 candidate proposal。
```

然后：

```text
使用 $ai-knowledge-governance，review 上一步 candidate，展示 digest、相关 approved entries 和 promote/reject/leave unchanged 选择。
```

期望：reflection 先 `workflow reflect-submit`，再 `wiki propose`；governance 只在明确人类选择后执行 digest-protected lifecycle 命令。

## 6. Git Handoff

Prompt:

```text
使用 $ai-git-handoff，检查本地变更并给我 skip、commit current branch、create branch/MR 三个选择。不要自动提交或 push。
```

## Evidence Template

```text
client:
client_version:
repo_commit:
skill_digests:
  ai-workflow-init:
  ai-workflow-harness:
  ai-small-tdd-change:
  ai-git-handoff:
  ai-knowledge-reflection:
  ai-knowledge-governance:
run_id:
attempt_ids:
final_status:
reflection_outcome:
candidate_id:
governance_decision:
manual_interventions:
recovery_prompt_result:
git_handoff_choice:
doctor_result:
notes:
```
