# Candidate Proposal and Human Knowledge Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic candidate proposal, human promotion/rejection/archive, and CLI lifecycle commands for the wiki.

**Architecture:** Add a dedicated proposal model that validates incoming proposal JSON and converts it into a candidate knowledge entry. Extend the repository with digest-aware move helpers so service methods can safely promote, reject, or archive files without rewriting the rest of the wiki stack. Wire the new commands into the existing JSON-envelope CLI and cover the flow with unit, contract, and end-to-end tests.

**Tech Stack:** Python 3.11, dataclasses, pathlib, hashlib, PyYAML, pytest, argparse.

## Global Constraints

- Keep the implementation deterministic and offline.
- Candidate proposals must validate required JSON fields, reject empty evidence, oversized raw logs, and unsupported confidence values.
- `propose` writes only to `wiki/candidates` and always forces candidate status.
- `promote` must verify the current digest, set status to approved, add reviewer/reviewed_at, validate references, and atomically move the file.
- `reject` archives with an appended lifecycle note containing reviewer and reason.
- `archive` applies the same digest guard to approved entries.
- Expose CLI commands: propose/promote/reject/archive.

---

### Task 1: Add proposal/model validation and digest helpers

**Files:**
- Modify: `src/ai_workflow/wiki/models.py`
- Test: `tests/unit/wiki/test_lifecycle.py`

**Interfaces:**
- Produces: `CandidateProposal.from_json(path: Path) -> CandidateProposal`
- Produces: `KnowledgeEntry.digest() -> str` or equivalent digest helper used by service/repository

- [ ] **Step 1: Write the failing test**

```python
def test_candidate_proposal_rejects_missing_required_fields(tmp_path):
    ...
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/unit/wiki/test_lifecycle.py -q`
Expected: fail because the proposal model does not exist yet.

- [ ] **Step 3: Write the minimal implementation**

Add the proposal dataclass, JSON parsing/validation, and any digest helper needed for lifecycle guards.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/unit/wiki/test_lifecycle.py -q`
Expected: pass.

### Task 2: Add repository lifecycle move helpers

**Files:**
- Modify: `src/ai_workflow/wiki/repository.py`
- Test: `tests/unit/wiki/test_lifecycle.py`

**Interfaces:**
- Produces: digest-aware move/write helpers used by `WikiService.propose/promote/reject/archive`

- [ ] **Step 1: Write the failing test**

```python
def test_promote_rejects_stale_candidate_digest(service, candidate):
    ...
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/unit/wiki/test_lifecycle.py -q`
Expected: fail because the service/repository lifecycle methods are missing.

- [ ] **Step 3: Write the minimal implementation**

Add safe file reads/digests and atomic lifecycle move helpers that preserve current repository invariants.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/unit/wiki/test_lifecycle.py -q`
Expected: pass.

### Task 3: Implement wiki lifecycle service methods

**Files:**
- Modify: `src/ai_workflow/wiki/service.py`
- Test: `tests/unit/wiki/test_lifecycle.py`

**Interfaces:**
- Produces: `WikiService.propose`, `WikiService.promote`, `WikiService.reject`, `WikiService.archive`

- [ ] **Step 1: Write the failing tests**

```python
def test_agent_proposal_is_written_only_to_candidates(service, proposal_path):
    ...

def test_reject_appends_lifecycle_note_and_archives(service, candidate):
    ...
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python -m pytest tests/unit/wiki/test_lifecycle.py -q`
Expected: fail because the methods are not implemented.

- [ ] **Step 3: Write the minimal implementation**

Parse proposals into candidate entries, verify digests on promote/archive, set reviewer metadata, validate references, append rejection notes, and move files safely.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/unit/wiki/test_lifecycle.py -q`
Expected: pass.

### Task 4: Wire CLI lifecycle commands and contract coverage

**Files:**
- Modify: `src/ai_workflow/cli.py`
- Create: `tests/contract/test_wiki_lifecycle_cli.py`
- Create: `tests/e2e/test_candidate_promotion.py`

**Interfaces:**
- Produces: CLI subcommands `wiki propose/promote/reject/archive`

- [ ] **Step 1: Write the failing CLI/e2e tests**

```python
def test_wiki_lifecycle_cli_round_trip(tmp_path, capsys):
    ...
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/contract/test_wiki_lifecycle_cli.py tests/e2e/test_candidate_promotion.py -q`
Expected: fail because the commands do not exist yet.

- [ ] **Step 3: Write the minimal implementation**

Add argparse wiring and JSON-envelope output for all lifecycle commands.

- [ ] **Step 4: Run the focused tests, then the full suite**

Run: `python -m pytest tests/unit/wiki/test_lifecycle.py tests/contract/test_wiki_lifecycle_cli.py tests/e2e/test_candidate_promotion.py -q`
Expected: pass.

Run: `python -m pytest -q`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/ai_workflow tests docs/superpowers/plans/2026-07-15-wiki-candidate-lifecycle.md
git commit -m "feat: add human-reviewed knowledge lifecycle"
```
