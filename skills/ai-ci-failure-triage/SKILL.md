---
name: ai-ci-failure-triage
description: Use when 用户要求收集 CI failed-job facts、分类失败并路由到正确 Skill。
---

# AI CI Failure Triage

CI triage 的目标是收集完整事实、分类失败、路由到正确 Skill。不要先猜修复。

## Loop

`collect facts -> classify -> route -> report`

## Required facts

先收集并展示：

- job URL
- commit
- branch
- stage
- command
- exit status
- bounded logs
- changed files
- environment variables 或 runner 信息中可公开的部分

缺少关键事实时先补采，不要直接改代码。

## Failure classes

- `environment failure`：权限、依赖服务、网络、runner、缓存、密钥、环境变量。
- `build failure`：编译、lint、依赖解析、类型检查。
- `unit-test failure`：单测断言、测试隔离、mock、fixture。
- `integration-test failure`：集成测试 case、环境、mock/fixture drift、跨服务契约。

## Routing

按 [failure routing](references/failure-routing.md) 路由。环境问题进入 blocked 或交给人类；build/unit 小修可转 `$ai-small-tdd-change` 或 `$ai-workflow-harness`；integration-test failure 转 `$ai-integration-test-v2`。**进入 blocked / 交给人类等待前**，若已配置通知通道，调用 `ai-workflow wecom notify --repo REPO --gate blocked --action "CI 环境失败，需人工补权限/环境/密钥或决策" --summary "<environment failure 摘要>"` 通知团队；失败仅写 warning，不影响主流程。

## Report

报告 failure class、证据、推荐路由、未采集到的事实和下一步。没有足够证据时输出“不足以分类”，不要伪造结论。
