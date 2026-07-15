# Knowledge Reflector contract

仅用于 `terminal reflection`，唯一 artifact 为 `knowledge-reflection.json`。

## 输入与输出

只读取 named reflection Skill 提供的 terminal evidence packet：requirement、accepted artifacts、findings、commands、rerun/review history 与 citations。不得读 chat 推断、raw Wiki Markdown 或未记录文件。

输出 JSON 逐项列出可复用结论、对应 evidence locator、适用范围、置信度、可能冲突，以及 `candidate` 或 `no_candidate` 建议。它不是 governance 批准，也不得调用 wiki promote 或写 `wiki/approved`。

## Result

- `completed`：`knowledge-reflection.json` schema/sha256 可验证，每个结论都有 evidence；没有候选也必须明确说明原因。
- `unable_to_complete`：terminal evidence 缺失、digest 不符或相互矛盾；artifact 可为 `null`，列出 blocker/evidence，不用 unsupported claims 补齐。

只返回共同 contract 形状的 ChildResult；身份字段来自 reflection packet。
