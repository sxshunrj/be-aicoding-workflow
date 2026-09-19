# Reflection Proposal Contract

`knowledge-reflection-decision.json` has exact keys:

```json
{
  "schema_version": 1,
  "run_id": "RUN-20260715-120000-abcdef",
  "evidence_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "outcome": "no_candidate",
  "reason": "Evidence is run-specific and not reusable."
}
```

`outcome` is `no_candidate` or `candidate`. `reason` must explain the evidence-backed decision.

For `candidate`, write a separate unchanged schema-v1 `CandidateProposal` JSON as `knowledge-proposal.json`. Do not add workflow-only fields to `CandidateProposal`. One proposal source must be exactly `{"kind": "run", "ref": run_id}`.

Allowed candidate types: `rule`, `pattern`, `diagnostic`, `decision`, `pitfall`, `workflow`, and existing-compatible `procedure` when the repository taxonomy allows it.

Evidence rules: forbid raw secrets, forbid invented claims, forbid direct approved writes. Use bounded packet evidence, cited knowledge, artifacts, findings, review/rerun history, and CLI search results only.
