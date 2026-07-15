---
name: ai-workflow
description: Use when coordinating or executing ai-workflow runs, writing or reviewing phase packets and ChildResult artifacts, or operating the repo's deterministic workflow/wiki lifecycle through the CLI.
---

# AI Workflow

## When to use

Use this skill for tasks that touch:
- `ai-workflow workflow ...`
- `ai-workflow wiki ...`
- phase packet / ChildResult generation
- skill-contract, phase-contract, or client-adapter updates

## Control Loop

`status -> begin -> dispatch phase worker -> collect ChildResult -> submit -> derive rerun proposal -> human Review Gate -> transition -> status`

Rules:
- The main agent schedules, summarizes, and checks artifacts. It does not perform phase work.
- Never edit state.yaml directly.
- Workers receive only the generated phase packet and required artifacts.
- Workers return a fixture-compatible ChildResult JSON file.
- Wiki content is consumed only through packet paths.
- Workers may propose candidates but never modify `wiki/approved`.
- Blocked, final completion, promotion, and destructive Git actions require humans.
- A new conversation resumes by calling `workflow status`, not by reconstructing state from chat history.
- Typical commands include `ai-workflow workflow submit` and `ai-workflow wiki propose`.

## Phase contracts

See [references/phase-contracts.md](references/phase-contracts.md) for the exact artifact filenames and responsibilities for `spec`, `plan`, `implement`, and `verify`.

## Client adapters

See [references/client-adapters.md](references/client-adapters.md) for the Codex and Claude Code dispatch mapping that preserves the same control loop.
