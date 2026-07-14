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

---

# AI Coding Workflow 与 Git-native LLM Wiki（中文版）

## 1. 概述

本项目将构建一套面向单团队、与编程语言无关的 AI Coding Workflow，并以 Agent Skill 作为产品入口。Workflow 采用最小化的 `spec -> plan -> implement -> verify` 生命周期，由 Python 3.11+ 核心提供确定性的状态迁移、产物校验、流程恢复和知识操作。

系统同时引入独立的 LLM Wiki 知识面。团队知识以可评审的 Markdown 和 YAML 存储在 Git 中。Workflow 的各阶段只检索小型、可引用的知识包，而不会把整个 Wiki 加载到上下文。Agent 可以在运行结束后提出候选知识，但只有人类可以将候选知识晋升为正式知识。

第一版通过轻量 Skill 适配 Codex 和 Claude Code，两种客户端共用同一套 CLI 和 JSON 协议。

## 2. 目标

- 从需求澄清到独立验证，完成一条可验证的 AI Coding 闭环。
- 将 Workflow 状态移出对话，使被中断的运行能够安全恢复。
- 将 Agent 的概率性判断与状态、Schema 等确定性约束分离。
- 允许团队持续积累可信工程知识，同时阻止 Agent 静默污染知识库。
- 依靠 Git 让知识可读、可评审、可追溯、可回滚。
- 通过仓库配置适配不同编程语言，不在引擎中写死语言假设。
- 让 Codex、Claude Code 和未来的 Agent 客户端复用同一个核心实现。

## 3. MVP 非目标

- 向量检索、Embedding 或远端索引服务。
- Web 管理后台。
- 多租户权限系统或跨机器调度。
- 自动晋升或自动合并候选知识。
- 自动解决互相冲突的正式规则。
- 生产环境发布编排。
- 通用插件框架或事件总线。

## 4. 产品边界

产品仍以 Skill 形式交付和触发，但 Skill 本身保持轻量：

- 定义主 Agent 的角色和阶段协议；
- 调用 Python CLI，不直接编辑状态；
- 将执行工作派发给阶段 Agent；
- 向用户展示 Review Gate 和阻塞决策；
- 不使用自然语言指令实现状态迁移、知识检索或 Schema 校验。

必须可靠、可测试的操作由 Python Core 负责。Markdown 和 YAML 是人类、Agent 与 CLI 共同使用的持久化协议。

## 5. 架构

### 5.1 组件

#### 客户端适配层

Codex 和 Claude Code 适配层使用各自支持的 Skill 格式暴露相同的 `ai-workflow` 行为。适配层将客户端特有的 Agent 派发和交互机制转换为统一协议，但不保存 Workflow 真值，也不包含业务规则。

如果不同客户端可以表达相同指令，项目只维护一份规范 Skill。只有在触发方式、子 Agent 派发或交互机制无法统一时，才增加客户端专属的薄适配层。

#### Workflow Core

Python Workflow Core 是确定性的控制面，负责：

- Run 的初始化和发现；
- Phase 与 Node 的状态迁移；
- Attempt 标识与幂等控制；
- Artifact 注册与摘要校验；
- Review Gate 和 blocked 状态记录；
- 中断后的流程恢复；
- 追加式状态事件；
- 面向阶段 Agent 的机器可读任务包。

Workflow Core 不编写业务代码、不执行代码评审，也不判断技术结论是否正确。Agent 提交语义判断，Core 只校验并记录合法迁移。

#### Wiki Core

Python Wiki Core 是独立的知识面，负责：

- 知识 Schema 校验与 lint；
- 结构化过滤和关键词检索；
- 确定性排序与结果数量控制；
- 生成带引用的知识包；
- 校验候选知识提案；
- 人工驱动的晋升、拒绝、归档和替代；
- 知识新鲜度与冲突警告；
- 记录每次 Run 实际使用的知识。

未来 Wiki Core 可以服务多个 Workflow。Workflow Core 只通过稳定的 Python 接口和 JSON CLI 协议调用它。

#### Agent Runtime Port

Workflow Core 不直接依赖某一种 Agent 客户端。Skill 实现 Agent Runtime Port，提供以下概念操作：

- 派发阶段任务；
- 在客户端支持时恢复已有阶段 Worker；
- 提供不可变任务包；
- 收集结构化 Child Result；
- 展示人工决策点。

MVP 不需要独立的 Runtime 守护进程。

#### Git 知识真源

正式知识和候选知识使用带 YAML Front Matter 的 Markdown 文件存储在 Git 中。Git 提供所有权、评审、历史、回滚和访问控制能力。未来增加的任何检索索引都只能是派生数据，并且必须能够从 Git 重建。

### 5.2 依赖规则

依赖统一向内：

```text
Client Skill -> CLI contracts -> Workflow Core -> domain-neutral models
                               -> Wiki Core     -> Git knowledge files
```

Workflow Core 可以调用 Wiki Core 的公开接口。Wiki Core 不得依赖 Workflow Core 内部实现；生成候选知识时，它只接收通用的 Run Evidence 协议。

## 6. 仓库目录

框架仓库的目标目录为：

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

接入后的业务仓库包含：

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

MVP 默认将团队 Wiki 放在框架仓库中。配置必须允许 Wiki 指向另一个已检出的本地 Git 仓库，并且不改变检索接口。

## 7. Workflow 模型

### 7.1 阶段

正式生命周期为：

```text
spec -> plan -> implement -> verify
```

- `spec`：澄清范围、约束、验收标准和明确不做的行为；
- `plan`：确定改动边界、任务顺序、风险和验证命令；
- `implement`：修改代码并生成实现报告；
- `verify`：根据 Spec 和配置的构建、测试命令独立验证实现。

每个阶段必须生成通过 Schema 校验的 Artifact。MVP 可以每个阶段只运行一个 Worker，但状态模型要支持未来增加多个并行子节点，而不改变阶段语义。

### 7.2 节点有效性

每个节点使用以下调度状态之一：

- `pending`：从未执行；
- `running`：当前 Attempt 正在持有该节点；
- `valid`：最近一次已接受的结果可以复用；
- `rerun`：节点已经失效，并携带非空、可执行的重跑原因；
- `blocked`：没有外部变化或人工决策就无法继续。

Run 的终态为 `done` 和 `aborted`。

### 7.3 状态迁移协议

主循环为：

```text
读取状态
  -> 准备阶段任务包和知识包
  -> 派发 Agent
  -> 提交结构化结果
  -> 校验 Artifact 并结算 Attempt
  -> 推导候选重跑节点
  -> Review Gate
  -> 迁移状态
  -> 再次读取状态
```

只有 CLI 可以修改 `state.yaml`。每次成功修改状态时，同时向 `events.jsonl` 追加一条事件。状态版本号用于阻止过期写入。具有相同 Run、Node、Attempt 和 Result Digest 的重复提交必须保持幂等。

### 7.4 失败路由

- 当前节点自身负责的问题，创建该节点的新 Attempt；
- 上游 Artifact 的问题，将负责的上游节点标记为 `rerun`，同时附带证据和可执行原因；
- 工具缺失、环境不可用或外部依赖未满足时进入 `blocked`，不得伪装为实现失败；
- 正式知识发生冲突或可能过期时，在知识包中明确警告；如果影响结果，必须交给人类裁决；
- 最大尝试次数策略用于防止无限循环，反复失败最终转为人工决策点。

## 8. 知识模型

### 8.1 生命周期

知识具有四种存储状态：

- `candidate`：由 Run 或人类提出，默认检索不使用；
- `approved`：经过评审，可以被正常检索；
- `archived`：保留历史，但不参与检索；
- `superseded`：已被其他条目替代，只有查询历史时才返回。

Agent 只能创建候选知识。晋升、拒绝、合并和替代必须是明确的人工操作，并通过 CLI 表达为 Git 变更。

### 8.2 条目格式

每个知识条目是一个带 YAML Front Matter 的 Markdown 文件。必填字段为：

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

Markdown 正文包含规则或决策、适用条件、原因、示例或反例，以及验证方式。可以通过版本化 Schema 兼容地增加字段，但在同一个主版本中不能改变必填字段的含义。

### 8.3 检索

MVP 检索必须可解释且结果确定：

1. 排除候选、已归档和已被替代的知识；
2. 在提供条件时，按仓库、服务、路径、语言、阶段、类型和标签过滤；
3. 将标准化查询词与标题、摘要、标签和正文匹配；
4. 精确 Scope 匹配优先于宽泛匹配，标题和标签命中优先于仅正文命中；
5. 对新鲜度和冲突发出警告，但不静默删除仍处于 approved 状态的条目；
6. 强制限制条目数量和字符数量。

每条结果都返回知识 ID、文件路径、命中原因、状态、新鲜度和冲突。排序规则由单元测试覆盖，且不调用 LLM。

### 8.4 知识包

Workflow 阶段只消费生成的知识包，不直接读取 Wiki 目录。知识包包含：

- 查询上下文和过滤条件；
- 选中的知识 ID 和源文件路径；
- 摘要和最小相关正文；
- 命中原因；
- 新鲜度或冲突警告；
- 知识包摘要值。

当阶段决策依赖 Wiki 内容时，阶段 Artifact 必须引用知识 ID。Run 记录知识包和引用使用情况，便于运行结束后判断知识是否有用或过期。

### 8.5 候选知识生成

Run 结束后，Agent 只接收有限的运行证据：Spec 摘要、已接受的 Artifact、验证发现、引用过的知识 ID 和人工反馈。Agent 可以针对决策、可复用模式、操作流程或踩坑经验等持久事实提出候选知识。

每个提案必须包含：

- 知识类型和建议 Scope；
- 持久化结论；
- 来源证据；
- 为什么该结论可以在本次 Run 之外复用；
- 置信度和潜在冲突；
- 建议 Owner 和复审日期。

Wiki Core 校验提案后，只能将其写入 `wiki/candidates/`。原始日志和未经验证的推测不能成为候选知识。

## 9. 配置

`.ai-workflow.yaml` 用于声明仓库特有行为，而不在引擎中写死语言假设。配置包括：

- 仓库和服务标识；
- Wiki 路径；
- 构建和测试命令；
- 可选的格式化或静态分析命令；
- Artifact 大小限制；
- 最大尝试次数；
- Review Gate 策略；
- 默认知识 Scope 和结果限制；
- 禁止 Agent 修改的路径。

命令应尽量避免隐式 Shell 展开。CLI 记录命令、工作目录、退出状态、持续时间和经过限制的输出证据。

## 10. CLI 与协议

稳定的命令分组为：

```text
ai-workflow workflow init|status|begin|submit|transition|block|resume|abort
ai-workflow wiki lint|search|packet|propose|promote|reject|archive
```

所有命令均支持 JSON 输出。成功和错误使用明确、机器可读的 Envelope。错误必须区分非法输入、非法迁移、状态过期、Artifact 缺失、知识冲突、环境失败和内部失败。

Artifact 与 Result 协议需要版本化。阶段任务包只包含该阶段必需的输入：Run 标识、当前 Spec 或 Plan、相关上游摘要、知识包路径和 Digest、工作区版本、配置命令，以及可能存在的重跑原因。

## 11. Review 与安全

- Workflow 默认使用人工 Review 模式；
- 只有 Artifact 通过 Schema 校验且 Review Gate 接受候选下一状态后，才能发生阶段迁移；
- MVP 中的 `blocked`、最终完成、知识晋升和破坏性 Git 操作始终需要明确的人工决策；
- Agent 不能通过 Workflow 直接编辑正式知识；
- 候选知识晋升前检查当前文件 Digest，防止审批过期内容；
- Artifact 记录其描述的源代码版本；
- Git 可用时，Verification 必须针对不可变的实现 Checkpoint 执行；
- Artifact 和 Wiki 条目中禁止保存密钥、原始凭据和无限量日志。

## 12. 测试策略

### 12.1 单元测试

单元测试覆盖：

- 所有合法与非法状态迁移；
- Attempt 所有权、过期写入和幂等提交；
- Artifact Schema 与 Digest 校验；
- 知识 Front Matter 校验；
- Scope 过滤与确定性排序；
- 新鲜度、冲突、归档和替代行为；
- 候选知识晋升和拒绝规则；
- 配置校验和安全命令构造。

### 12.2 协议测试

协议测试验证：

- JSON 请求和响应兼容性；
- Skill 到 CLI 的命令示例；
- 阶段任务包和 Child Result Fixture；
- Codex 和 Claude 适配层通过同一套一致性测试；
- Schema 版本行为和可执行错误信息。

### 12.3 端到端测试

使用临时 Git 仓库和确定性的 Fake Agent Runtime 验证：

- 完整四阶段 Run；
- Verification 发现问题并重跑 Implementation；
- Result 提交前和提交后的进程中断；
- 在新的客户端会话中恢复；
- 带引用的知识检索；
- 候选知识创建、人工晋升和后续检索；
- 知识冲突或过期警告；
- 环境阻塞和人工恢复。

默认测试套件不依赖网络服务。

## 13. 可观测性

`events.jsonl` 是 Run 的审计日志。事件包括 Run 初始化、Phase Begin、Agent Dispatch、Result Submit、Artifact Accept、Knowledge Packet Create、Review Gate Decision、State Transition、Block/Resume 和 Terminal Complete。

事件包含稳定 ID、时间戳、状态版本、Attempt ID、Artifact Digest 和知识 ID，但不保存完整 Prompt 或密钥。Summary 命令根据事件日志计算阶段耗时、尝试次数、重跑次数、人工干预次数和知识使用情况。

## 14. MVP 验收标准

同时满足以下条件时，MVP 才算完成：

1. `workflow init` 可以通过 `.ai-workflow.yaml` 接入任意 Git 仓库；
2. 一个任务完整执行 `spec -> plan -> implement -> verify`，并且每个阶段都有通过校验的 Artifact；
3. 每个阶段都能根据 Scope 和关键词获得有限知识包；
4. 阶段 Artifact 可以引用知识 ID，Run 会记录这些引用；
5. Run 完成后可以生成通过校验的候选知识；
6. 人类可以通过 CLI 晋升候选知识，晋升后该条目能作为正式知识被检索；
7. Run 中断后，可以在新的 Agent 对话中从正确状态恢复；
8. Verification 可以将可执行 Finding 退回 Implementation，而不重启整个 Run；
9. Codex 和 Claude Code 使用相同 Python Core 和协议 Fixture 完成同一个示例 Workflow；
10. 单元测试、协议测试和端到端测试在无网络环境下全部通过。

## 15. 交付顺序

实现按以下纵向增量推进：

1. Python Package 骨架、领域无关协议和 CLI Envelope；
2. Workflow 状态机、事件日志和恢复；
3. Artifact 协议和使用 Fake Agent 的端到端 Run；
4. Git Wiki Schema、Lint、检索和知识包；
5. 候选知识提案和人工晋升 Workflow；
6. 规范 Skill，以及 Codex 和 Claude 的一致性适配；
7. 与语言无关的示例仓库和完整 MVP 验收测试。

每个增量都必须保持可运行并通过测试。在 Git-native 闭环得到验证前，设计明确不建设通用事件总线、服务层或向量索引。
