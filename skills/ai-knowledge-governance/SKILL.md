---
name: ai-knowledge-governance
description: Use when reviewing ai-workflow candidate knowledge for human promotion, rejection, or leaving it unchanged.
---

# AI Knowledge Governance

Knowledge governance is a human gate. The Agent gathers facts, compares material differences, and executes only the chosen digest-protected lifecycle action.

## Sequence

`wiki review -> inspect candidate evidence, scope, reuse reason, conflicts, expiry, and related approved entries -> show digest and material differences -> human choice -> execute exactly one digest-protected lifecycle command -> report result`

Run `ai-workflow wiki review --wiki PATH --id ID` first. Read the candidate digest, declared conflicts/supersedes, and related approved entries. Apply the [review checklist](references/review-checklist.md) before presenting choices.

Human choices are `promote`, `reject`, or `leave candidate unchanged`. No choice may default to promote; silence means leave unchanged.

If the human chooses `promote`, run `wiki promote` with the candidate `expected-digest`. If the human chooses `reject`, run `wiki reject` with `expected-digest` and the explicit reason. Do not archive approved entries from this candidate flow unless the human starts a separate approved-retirement action.

Report the resulting approved path/searchability, archived path, or unchanged candidate ID and digest.
