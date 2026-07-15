# AI Workflow

Status: MVP verified

This repository implements a local, deterministic AI coding workflow with a wiki-backed knowledge loop.

## Getting Started

1. Install Python 3.11 or newer.
2. Install dependencies with `pip install -e '.[dev]'`.
3. Copy `examples/language-neutral/.ai-workflow.yaml` into your repository root and edit the repository-specific values: repository name, wiki path, commands, and protected paths.
4. Drive the workflow from Codex or Claude Code with the `ai-workflow` skill. Use it to begin a run, submit a phase result, and transition only when the workflow requires a rerun decision.
5. Inspect a run with `ai-workflow workflow status --repo <repo> --run-id <run_id>`, then resume from the recorded `current_phase` and attempt data.
6. Work with the wiki locally:
   - lint it with `ai-workflow wiki lint --wiki <wiki>`;
   - search it with `ai-workflow wiki search --wiki <wiki> --repository <repo> --text <query>`.
7. Review and promote candidate knowledge with digest protection:
   - `ai-workflow wiki propose --wiki <wiki> --proposal <proposal.json>`;
   - `ai-workflow wiki promote --wiki <wiki> --id <candidate_id> --reviewer <name> --expected-digest <sha256>`.
8. Run the offline test suite with `python -m pytest -q`.

## Example

The `examples/language-neutral` directory shows a language-neutral setup that keeps build and test commands in config only and stores wiki content in a sibling `../../wiki` directory.
