# Dispatch

implement 和 verify 使用 child-backed 执行。

- 只把 Helper 生成的 `prompt_file` 交给 child。
- child 只返回 schema-v2 `ChildResult`。
- 主 Agent serially `stage` 每个 child result。
- `barrier` 未满足时不得 `finalize`。
- `finalize` 后才进入 review gate。
