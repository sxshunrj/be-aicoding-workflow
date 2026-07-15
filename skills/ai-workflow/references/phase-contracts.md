# Phase Contracts

Each phase worker receives the generated phase packet plus only the artifacts named for that phase. It returns a ChildResult JSON file that the main agent can submit unchanged.

| Phase | Worker responsibility | Main artifact |
| --- | --- | --- |
| `spec` | Turn the packet and wiki context into the technical contract. | `technical-spec.md` |
| `plan` | Turn the technical contract into an implementation plan. | `implementation-plan.md` |
| `implement` | Produce the implementation report and any code changes. | `implementation-report.md` |
| `verify` | Summarize verification results and unresolved risks. | `verification-report.md` |

Rules:
- Workers do not edit `state.yaml`.
- Workers do not read wiki Markdown directly; they use the packet paths.
- Workers may propose candidates, but only the human can promote or reject them.
- The returned ChildResult JSON must match `tests/contract/fixtures/*-result.json`.
