# AI Coding Workflow with Git-native LLM Wiki

## 1. Summary

Build a team-oriented, language-agnostic AI coding workflow delivered as an Agent Skill. The workflow follows a minimal `spec -> plan -> implement -> verify` lifecycle and uses a Python 3.11+ core for deterministic state transitions, artifact validation, recovery, and knowledge operations.

The system adds an LLM Wiki knowledge plane. Team knowledge is stored as reviewable Markdown and YAML in Git. Workflow phases retrieve small, cited knowledge packets instead of loading the whole Wiki. Agents may propose candidate knowledge after a run, but only humans may promote candidates into approved knowledge.

The first release supports Codex and Claude Code through thin Skill adapters that share the same CLI and JSON contracts.

## 2. Goals

- Run one verifiable AI coding loop from requirement clarification through independent verification.
- Keep workflow state outside the conversation so interrupted runs can resume safely.
- Separate probabilistic Agent decisions from deterministic state and schema enforcement.
- Let a team accumulate trusted engineering knowledge without allowing Agents to silently pollute it.
- Keep knowledge human-readable, reviewable, versioned, and reversible through Git.
- Support different programming languages through repository configuration rather than built-in language assumptions.
- Reuse one core implementation from Codex, Claude Code, and future Agent clients.

## 3. Non-goals for the MVP

- Vector search, embeddings, or a remote indexing service.
- A web administration UI.
- Multi-tenant authorization or cross-machine scheduling.
- Automatic promotion or merge of candidate knowledge.
- Automatic resolution of conflicting approved rules.
- Production deployment orchestration.
- A universal plugin or event-bus framework.

## 4. Product Boundary

The product is still delivered and invoked as a Skill. The Skill is intentionally thin:

- It defines the main Agent's role and phase protocol.
- It invokes the Python CLI instead of editing state directly.
- It dispatches execution to phase-specific Agents.
- It presents review and blocked-state decisions to the user.
- It does not implement state transitions, knowledge search, or schema validation in natural-language instructions.

The Python core owns operations that must be deterministic and testable. Markdown and YAML are the durable interfaces shared by humans, Agents, and the CLI.

## 5. Architecture

### 5.1 Components

#### Client adapters

Codex and Claude Code adapters expose the same `ai-workflow` behavior in each client's Skill format. They translate client-specific Agent dispatch and interaction mechanisms into a shared protocol. They do not store workflow truth or contain business rules.

The project should maintain one canonical Skill whenever the clients support equivalent instructions. Client-specific adapters are added only where invocation, sub-agent dispatch, or interaction mechanics cannot be expressed portably.

#### Workflow Core

The Python Workflow Core is the deterministic control plane. It owns:

- run initialization and discovery;
- phase and node state transitions;
- attempt identity and idempotency;
- artifact registration and digest validation;
- Review Gate and blocked-state records;
- recovery from interrupted execution;
- append-only transition events;
- machine-readable packets for phase Agents.

It does not write business code, perform code review, or decide technical correctness. Agents make semantic proposals; the core validates and records legal transitions.

#### Wiki Core

The Python Wiki Core is an independent knowledge plane. It owns:

- knowledge schema validation and linting;
- structured filtering and keyword retrieval;
- deterministic ranking and result limits;
- generation of cited knowledge packets;
- candidate proposal validation;
- human-driven promotion, rejection, archival, and supersession;
- freshness and conflict warnings;
- recording which knowledge entries were used by a run.

The Wiki Core can serve more than one workflow in the future. Workflow Core consumes it through stable Python interfaces and JSON CLI contracts.

#### Agent Runtime Port

Workflow Core does not directly depend on a particular Agent client. The Skill implements an Agent Runtime port with these conceptual operations:

- dispatch a phase task;
- resume a known phase worker when supported;
- provide an immutable task packet;
- collect a structured child result;
- present a human decision point.

The MVP does not require a standalone runtime daemon.

#### Git knowledge source of truth

Approved and candidate knowledge lives in Git as Markdown with YAML front matter. Git provides ownership, review, history, rollback, and access control. Any future search index is derived data and must be rebuildable from Git.

### 5.2 Dependency Rule

Dependencies point inward:

```text
Client Skill -> CLI contracts -> Workflow Core -> domain-neutral models
                               -> Wiki Core     -> Git knowledge files
```

Workflow Core may call the public Wiki Core interface. Wiki Core must not depend on Workflow Core internals; it receives a generic run evidence contract when proposing knowledge.

## 6. Repository Layout

The framework repository starts with this target layout:

```text
ai-coding-workflow/
├── skills/
│   └── ai-workflow/
│       ├── SKILL.md
│       └── references/
├── src/
│   └── ai_workflow/
│       ├── workflow/
│       ├── wiki/
│       ├── contracts/
│       └── cli.py
├── wiki/
│   ├── approved/
│   ├── candidates/
│   ├── archive/
│   └── taxonomy.yaml
├── templates/
├── examples/
├── tests/
├── docs/
│   └── superpowers/specs/
└── pyproject.toml
```

An integrated business repository contains:

```text
business-repo/
├── .ai-workflow.yaml
└── .ai-workflow/
    ├── runs/<run-id>/
    │   ├── state.yaml
    │   ├── events.jsonl
    │   ├── artifacts/
    │   ├── results/
    │   └── knowledge-packets/
    └── archive/
```

The default MVP keeps the team Wiki in the framework repository. Configuration must allow a local path to a separately checked-out Git Wiki later without changing the retrieval interface.

## 7. Workflow Model

### 7.1 Phases

The formal lifecycle is:

```text
spec -> plan -> implement -> verify
```

- `spec`: clarify scope, constraints, acceptance criteria, and excluded behavior.
- `plan`: identify change boundaries, task order, risks, and verification commands.
- `implement`: modify code and produce an implementation report.
- `verify`: independently evaluate the implementation against the spec and configured build/test commands.

Each phase emits a schema-validated artifact. The MVP may run one worker per phase; the state model supports multiple sibling nodes later without changing phase semantics.

### 7.2 Node validity

Each node uses one of these scheduling states:

- `pending`: never executed;
- `running`: an attempt owns the node;
- `valid`: the latest accepted result can be reused;
- `rerun`: the node is invalid and carries a non-empty actionable reason;
- `blocked`: the node cannot proceed without an external change or human decision.

Terminal run states are `done` and `aborted`.

### 7.3 State transition protocol

The main loop is:

```text
read state
  -> prepare phase packet and knowledge packet
  -> dispatch Agent
  -> submit structured result
  -> validate artifact and settle attempt
  -> derive candidate reruns
  -> Review Gate
  -> transition state
  -> read state again
```

Only CLI commands may modify `state.yaml`. Every accepted mutation appends an event to `events.jsonl`. A state version prevents stale writes. Repeated submission with the same run, node, attempt, and result digest is idempotent.

### 7.4 Failure routing

- A problem owned by the current node causes a new attempt of that node.
- An upstream artifact problem marks the responsible upstream node `rerun` with evidence and an actionable reason.
- Missing tools, unavailable environments, or unresolved external dependencies enter `blocked`; they are not represented as implementation failures.
- Conflicting or stale approved knowledge is included as an explicit warning and requires human adjudication when it affects the result.
- A maximum attempt policy prevents infinite loops and converts repeated failure into a human decision point.

## 8. Knowledge Model

### 8.1 Lifecycle

Knowledge has four storage states:

- `candidate`: proposed from run evidence or written by a human, not used by default retrieval;
- `approved`: reviewed and eligible for normal retrieval;
- `archived`: retained for history but excluded from retrieval;
- `superseded`: replaced by another entry and excluded unless history is requested.

Agents may create candidates only. Promotion, rejection, merge, and supersession are explicit human actions expressed as Git changes through the CLI.

### 8.2 Entry format

Each entry is one Markdown file with YAML front matter. Required fields are:

```yaml
id: KW-architecture-001
title: Payment command must use an idempotency key
type: decision
status: approved
summary: Short retrieval-oriented summary
scope:
  repos: [payment-service]
  services: [payment]
  paths: [src/domain/**]
  languages: [java]
  phases: [plan, implement, verify]
tags: [idempotency, payment]
owners: [team-payment]
reviewers: [alice]
created_at: 2026-07-14
reviewed_at: 2026-07-14
review_after: 2026-10-14
sources:
  - kind: run
    ref: RUN-20260714-001
supersedes: []
conflicts_with: []
```

The Markdown body contains the rule or decision, applicability conditions, rationale, examples or counterexamples, and verification guidance. Fields may be added compatibly through a versioned schema, but required field meaning must remain stable within a major schema version.

### 8.3 Retrieval

MVP retrieval is explainable and deterministic:

1. Exclude candidates, archived entries, and superseded entries.
2. Filter by repository, service, path, language, phase, type, and tags when supplied.
3. Match normalized query terms against title, summary, tags, and body.
4. Rank exact scope matches ahead of broad matches, then title/tag matches ahead of body-only matches.
5. Apply freshness and conflict warnings without silently removing a still-approved entry.
6. Enforce configurable entry and character limits.

Every result reports the knowledge ID, file path, matching reason, status, freshness, and any conflicts. Ranking rules are unit tested and do not call an LLM.

### 8.4 Knowledge packets

Workflow phases consume a generated packet rather than the Wiki directory. A packet includes:

- query context and filters;
- selected entry IDs and source paths;
- summaries and the minimum relevant content;
- match reasons;
- freshness or conflict warnings;
- a packet digest.

Phase artifacts cite knowledge IDs when a decision relies on Wiki content. The run records packet and citation usage so later reflection can evaluate usefulness or staleness.

### 8.5 Candidate generation

At run completion, an Agent receives bounded run evidence: the spec summary, accepted artifacts, verification findings, cited knowledge IDs, and human feedback. It may propose candidate entries for durable facts such as decisions, reusable patterns, procedures, or pitfalls.

Each proposal must include:

- a knowledge type and proposed scope;
- the durable claim;
- source evidence;
- why the claim is reusable beyond this run;
- confidence and possible conflicts;
- suggested owner and review date.

Wiki Core validates the proposal and writes it only under `wiki/candidates/`. Raw logs and unverified speculation must not become candidates.

## 9. Configuration

`.ai-workflow.yaml` declares repository-specific behavior without embedding language assumptions in the engine. It includes:

- repository and service identity;
- Wiki path;
- build and test commands;
- optional formatting or static-analysis commands;
- artifact size limits;
- maximum attempts;
- Review Gate policy;
- knowledge scope defaults and result limits;
- paths excluded from Agent edits.

Commands execute without implicit shell expansion where possible. The CLI records command, working directory, exit status, duration, and bounded output evidence.

## 10. CLI and Contracts

The stable command groups are:

```text
ai-workflow workflow init|status|begin|submit|transition|block|resume|abort
ai-workflow wiki lint|search|packet|propose|promote|reject|archive
```

All commands support JSON output. Success and error envelopes are explicit and machine-readable. Errors identify whether the cause is invalid input, illegal transition, stale state, missing artifact, knowledge conflict, environment failure, or internal failure.

Artifact and result contracts are versioned. A phase packet includes only the inputs required by that phase: run identity, current spec or plan, relevant prior summaries, knowledge packet path and digest, workspace revision, configured commands, and any rerun reason.

## 11. Review and Safety

- The workflow starts in human-review mode.
- A phase transition occurs only after its artifact passes schema validation and the Review Gate accepts the proposed next state.
- `blocked`, final completion, knowledge promotion, and destructive Git actions always require an explicit human decision in the MVP.
- Agents cannot directly edit approved knowledge through the workflow.
- Candidate promotion checks the current file digest to prevent approving stale content.
- Artifacts record the source code revision they describe.
- Verification runs against an immutable implementation checkpoint when Git is available.
- Secrets, raw credentials, and unbounded logs are prohibited in artifacts and Wiki entries.

## 12. Testing Strategy

### 12.1 Unit tests

Unit tests cover:

- every legal and illegal state transition;
- attempt ownership, stale writes, and idempotent submission;
- artifact schema and digest validation;
- knowledge front-matter validation;
- scope filtering and deterministic ranking;
- freshness, conflict, archive, and supersession behavior;
- candidate promotion and rejection rules;
- configuration validation and safe command construction.

### 12.2 Contract tests

Contract tests verify:

- JSON request and response compatibility;
- Skill-to-CLI command examples;
- phase packet and child result fixtures;
- Codex and Claude adapters against the same conformance suite;
- schema version behavior and actionable errors.

### 12.3 End-to-end tests

A temporary Git repository and a deterministic fake Agent runtime exercise:

- one complete four-phase run;
- a verification finding that reruns implementation;
- a process interruption before and after result submission;
- recovery in a new client session;
- knowledge retrieval with citations;
- candidate creation, human promotion, and subsequent retrieval;
- conflicting or stale knowledge warnings;
- a blocked environment and human resume.

No network service is required for the default test suite.

## 13. Observability

`events.jsonl` is the audit trail for a run. Events include run initialization, phase begin, Agent dispatch, result submission, artifact acceptance, knowledge packet creation, Review Gate decisions, state transitions, block/resume, and terminal completion.

Events contain stable IDs, timestamps, state versions, attempt IDs, artifact digests, and knowledge IDs, but not full prompts or secrets. A summary command derives phase duration, attempts, reruns, human interventions, and knowledge usage from the event log.

## 14. MVP Acceptance Criteria

The MVP is complete when all of the following are demonstrated:

1. `workflow init` can integrate an arbitrary Git repository using `.ai-workflow.yaml`.
2. One task completes `spec -> plan -> implement -> verify`, with a validated artifact for every phase.
3. Every phase can receive a bounded knowledge packet selected by scope and keywords.
4. Phase artifacts can cite knowledge IDs, and the run records those citations.
5. Completion can produce a validated candidate knowledge entry.
6. A human can promote that candidate through the CLI, after which it becomes retrievable as approved knowledge.
7. An interrupted run resumes from the correct state in a new Agent conversation.
8. Verification can send an actionable finding back to implementation without restarting the whole run.
9. Codex and Claude Code adapters complete the same example workflow using the same Python core and contract fixtures.
10. Unit, contract, and end-to-end tests pass without a network dependency.

## 15. Delivery Sequence

Implementation should proceed as vertical increments:

1. Package skeleton, domain-neutral contracts, and CLI envelope.
2. Workflow state machine, event log, and recovery.
3. Artifact contracts and a fake Agent end-to-end run.
4. Git Wiki schema, lint, search, and knowledge packets.
5. Candidate proposal and human promotion workflow.
6. Canonical Skill plus Codex and Claude conformance adapters.
7. A language-neutral example repository and full MVP acceptance test.

Each increment must remain executable and tested; the design intentionally avoids building a general event bus, service layer, or vector index before the Git-native loop is proven.
