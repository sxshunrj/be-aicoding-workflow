# Language-Neutral Example

这个示例只依赖本地文件，用来验证 Wave 1 的通用仓库接入方式。

本仓库配置使用 schema v2，启用 `build` 和 `unit_test` 两个命令节点，并显式关闭 `verify.integration_test`。运行：

```bash
bash verify.sh build
bash verify.sh unit-test
```

`.ai-workflow.yaml` 指向 sibling `../../wiki` 作为知识库，适合离线 E2E 和真实 Codex trial 复用。
