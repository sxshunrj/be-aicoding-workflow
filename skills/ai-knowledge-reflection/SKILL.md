---
name: ai-knowledge-reflection
description: Use when ai-workflow run is completed or aborted and terminal cleanup needs evidence-backed knowledge reflection.
---

# AI Knowledge Reflection

Terminal reflection turns recorded run evidence into either an explicit no-candidate decision or one candidate proposal. It is not governance.

## Sequence

`workflow reflect -> read packet -> search related approved knowledge -> write decision -> optional proposal -> workflow reflect-submit -> wiki propose`

Run only when `workflow status` is `completed` or `aborted`. First call `ai-workflow workflow reflect --repo REPO --run-id RUN`, read the packet, and use CLI search for related approved knowledge. Do not use chat memory as evidence.

Write `knowledge-reflection-decision.json` using the exact shape in [proposal contract](references/proposal-contract.md). If outcome is `no_candidate`, submit only that file with `workflow reflect-submit` and report the reason.

If outcome is `candidate`, also write `knowledge-proposal.json` as unchanged schema-v1 `CandidateProposal` JSON. It must include the current run source. Submit both files with `workflow reflect-submit`; only after that succeeds, call `wiki propose`.

## Boundaries

- never call `wiki promote`
- never write `wiki/approved`
- reflection acceptance is not governance approval
- do not invent claims
- do not include secrets
- for existing approved knowledge conflicts, mention them in the proposal rather than resolving them
