# Client Adapters

Use the same workflow semantics everywhere. Only the orchestration primitive changes.

| Control loop step | Codex adapter | Claude Code adapter |
| --- | --- | --- |
| Dispatch phase worker | Spawn or follow up a dedicated sub-agent with the phase packet and required artifacts. | Create a task/agent with the same packet and artifact scope. |
| Collect ChildResult | Wait for the worker to write its fixture-compatible JSON result, then read that file. | Read the task result artifact from the same contract file. |
| Human Review Gate | Ask the human to approve or reject the rerun proposal before `workflow transition`. | Ask the human the same review question before transition. |

Do not change the underlying contract:
- `workflow begin` creates the packet.
- the worker only sees the packet and required artifacts.
- `workflow submit` consumes the ChildResult file.
- `workflow status` is the restart point after a fresh conversation.
