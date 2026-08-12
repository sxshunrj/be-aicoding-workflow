---
name: ai-git-handoff
description: Use when 用户显式要求 Git handoff、收尾提交、创建分支或 MR，或 ai-workflow terminal cleanup 已被人类接受后需要处理本地变更。
---

# AI Git Handoff

Git 收尾是人类 gate。先取证，再给选择；没有选择就不改 Git。

## Flow

`inspect status/diff/current branch -> summarize intended task files and unrelated files -> human choice -> execute only the chosen scope -> report evidence`

## Inspect first

运行并阅读 `git status --short`、当前分支、任务相关文件的 `git diff --`，以及已暂存内容的 `git diff --cached`。区分本次任务文件、生成物、未跟踪文件和 unrelated user edits；不要凭记忆判断。

## Choices

- choice: `skip`
- choice: `commit current branch`
- choice: `create branch/MR`

向人类展示以上三个选择和每个选择会包含的文件。`execute only the chosen scope`：只 stage 人类确认的任务文件；Never stage unrelated files。

展示选择前，若已配置通知通道，调用 `ai-workflow wecom notify --gate git_handoff --action "请选择 skip / commit / MR"` 通知团队；失败仅写 warning，不影响主流程。

## Authorization gates

任何 push、remote branch、MR、destructive cleanup、`reset`、`clean`、`amend`、`force-push` 都必须在执行点再次获得 explicit authorization at the point of action。不要把“finish everything”解释为授权这些动作。

## Execution rules

- skip：不执行 Git mutation，只报告当前状态和剩余文件。
- commit current branch：确认文件清单后 `git add` 指定路径，再提交；不推送。
- create branch/MR：确认分支名、文件清单、push 和 MR 目标后再执行；缺少任一决定就停下。

## Report

最后报告 commit hash、branch、MR 链接或 skip 结果，以及未处理的 unrelated files。若验证未跑或失败，必须如实说明。
