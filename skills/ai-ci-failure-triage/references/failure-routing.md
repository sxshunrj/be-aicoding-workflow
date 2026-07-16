# Failure Routing

## Routes

| Failure class | Route |
| --- | --- |
| `environment failure` | 进入 `blocked`，要求人类补权限、环境、密钥或 runner 证据 |
| `build failure` | 小范围修复走 `$ai-small-tdd-change`；跨模块或公共接口走 `$ai-workflow-harness` |
| `unit-test failure` | 小范围行为回归走 `$ai-small-tdd-change`；复杂实现回归走 `$ai-workflow-harness` |
| `integration-test failure` | 走 `$ai-integration-test-v2`，先执行诊断和归因 |

## Required evidence

每次路由前必须记录 job URL、commit、stage、command、exit status 和 bounded logs。证据不足时不要开始修复。
