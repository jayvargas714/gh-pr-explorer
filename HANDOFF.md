# Agent Handoff — Generic Review Workflow Engine

## What This Project Is

A fork of [jayvargas714/gh-pr-explorer](https://github.com/jayvargas714/gh-pr-explorer) being transformed into a **generic workflow engine** for code review. Instead of a hardcoded single-pass Claude review, the system supports composable pipelines of typed steps (agent review, synthesis, human gates, publication) with fan-out/fan-in parallelism. Our adversarial review modes and Jay's original review become pre-built workflow templates.

**Fork:** `amartinat-scala/gh-pr-explorer`
**Upstream:** `jayvargas714/gh-pr-explorer` (remote: `upstream`)
**Target repo for reviews:** `scala-computing/scala`

## Architecture

```
Flask backend (Python)  +  React 18 / TypeScript frontend (Vite)
SQLite persistence (pr_explorer.db, auto-created)
State management: Zustand
External tools: gh CLI, Claude CLI, OpenAI API, acli (Jira)
```

### New packages added by this fork

```
backend/
├── agents/                    # Pluggable AI agent backends
│   ├── base.py                # AgentBackend ABC, AgentHandle, AgentStatus, ReviewArtifact
│   ├── claude_cli.py          # ClaudeCLIAgent — wraps subprocess calls to `claude`
│   ├── openai_api.py          # OpenAIAgent — OpenAI chat completions via httpx
│   └── registry.py            # get_agent(name), list_agents(), agent type registry
│
├── workflows/                 # Generic workflow engine
│   ├── step_types.py          # StepType enum, @register_step decorator, STEP_REGISTRY
│   ├── executor.py            # StepExecutor ABC, StepResult dataclass
│   ├── runtime.py             # WorkflowRuntime — topo-sort execution, fan-out, gate pausing
│   ├── seed.py                # Built-in templates (Quick/Team/Self/Deep Review) + agents
│   └── executors/             # Step executor implementations
│       ├── pr_select.py       # Fetches PRs via gh CLI
│       ├── prioritize.py      # P0-P3 scoring, code owner boost, skip list
│       ├── prompt_generate.py # Prompt building with dedup + Jira context + chunked diff
│       ├── agent_review.py    # Dispatches prompt to AgentBackend, polls, collects artifact
│       ├── synthesis.py       # Diffs Review A vs B, classifies AGREED/A-ONLY/B-ONLY
│       ├── freshness_check.py # Compares HEAD SHA at review time vs current
│       ├── human_gate.py      # Pauses workflow, presents gate payload to human
│       └── publish.py         # Posts to GitHub (gh pr review/comment), comment sanitization
│
├── database/
│   └── workflows.py           # CRUD for templates, instances, steps, artifacts, agents
│
└── routes/
    └── workflow_engine_routes.py  # Template CRUD, instance lifecycle, gate actions, agent list
```

### DB tables added

**Phase 1 (committed):** `workflow_templates`, `workflow_instances`, `instance_steps`, `instance_artifacts`, `agents`, `agent_name` column on `reviews`

**Phase 2 (uncommitted):** `code_owner_registry`, `skip_list`

### Frontend additions

- `frontend/src/api/workflow-engine.ts` — API client for templates, instances, agents
- `frontend/src/stores/useWorkflowEngineStore.ts` — Zustand store for workflow engine state
- `Review` type extended with `agent_name` field
- `startReview()` API accepts optional `agent` parameter
- `ReviewButton` shows agent name on completed reviews

### Config changes

`config.json` now includes an `agents` section and `default_repo`:

```json
{
  "agents": {
    "claude": { "type": "claude_cli", "model": "opus" },
    "openai": { "type": "openai_api", "model": "gpt-4o", "api_key_env": "OPENAI_API_KEY" }
  },
  "default_repo": "scala-computing/scala"
}
```

## Git Strategy

- **`main`** — always deployable; Jay's features never break
- **One feature branch per plan phase** — merged via PR when acceptance criteria pass
- **Conventional commits** — `feat:`, `fix:`, etc.

### Branches

| Branch | Status | Description |
|--------|--------|-------------|
| `phase1/workflow-model` | **Merged to main** | Agent abstraction, workflow data model, Quick Review template |
| `phase2/team-review` | **In progress** | Step executors for Team Review, Runs UI |

### Remotes

- `origin` → `amartinat-scala/gh-pr-explorer` (our fork)
- `upstream` → `jayvargas714/gh-pr-explorer` (Jay's original)

## Current State

### Phase 1 — COMPLETE (merged to main, pushed to origin)

Everything listed in the architecture section above is committed and verified:
- All imports pass
- DB schema creates correctly with all tables
- Seed data creates 4 built-in templates + 2 agents
- `review_service.py` refactored to use `AgentBackend` (backwards compatible)
- Existing Jay features (PRs, analytics, queue, history) unaffected

### Phase 2 — IN PROGRESS (branch: `phase2/team-review`)

**Done (uncommitted on branch):**
- `SynthesisExecutor` — diffs two reviews, classifies AGREED/A-ONLY/B-ONLY, computes verdict
- `FreshnessCheckExecutor` — SHA comparison, CURRENT/STALE-MINOR/STALE-MAJOR classification
- `PublishExecutor` — builds GitHub comment, sanitizes (strips `#N`, AI branding), posts via `gh pr review/comment`
- `PrioritizeExecutor` — P0-P3 scoring with code owner boost, skip list, draft exclusion, label parsing, age scoring
- `PromptGenerateExecutor` enhanced — prior review dedup, Jira context via `acli`, large diff chunked strategy
- `code_owner_registry` and `skip_list` DB tables added to `base.py`

**Remaining for Phase 2:**
- Frontend: `WorkflowRunList` component (table of instances with status badges)
- Frontend: `WorkflowRunDetail` component (step progress node graph with status colors)
- Frontend: `GatePanel` component (per-PR verdict, freshness badge, approve/reject/edit)
- Frontend: "Workflows" tab integration in main nav
- Integration test: end-to-end Team Review run through all executors
- Commit and merge to main

### Phases 3-6 — PENDING

See the full plan at the bottom of this file.

## How to Continue

### Running the app

```bash
pip install -r requirements.txt
cd frontend && npm install && cd ..

# Two terminals:
python3 app.py                    # Flask API → http://127.0.0.1:5714
cd frontend && npm run dev        # Vite → http://localhost:3050
```

### Verifying Phase 1

```bash
python3 -c "
import sys; sys.path.insert(0, '.')
import backend.workflows.executors  # registers all executors
from backend.workflows.step_types import STEP_REGISTRY
print('Registered executors:', list(STEP_REGISTRY.keys()))
from backend.workflows.seed import BUILTIN_TEMPLATES
print('Built-in templates:', len(BUILTIN_TEMPLATES))
print('OK')
"
```

### Adding a new step executor

1. Create `backend/workflows/executors/my_step.py`
2. Subclass `StepExecutor`, implement `execute(inputs) -> StepResult`
3. Decorate with `@register_step("my_step_type")`
4. Import in `backend/workflows/executors/__init__.py`
5. Add a config panel component in the frontend (Phase 4+)

### Key files to read first

- `backend/workflows/runtime.py` — the execution engine (topo sort, fan-out, gate pausing)
- `backend/agents/base.py` — the agent abstraction interface
- `backend/workflows/seed.py` — all 4 built-in template definitions (Quick/Team/Self/Deep)
- `backend/routes/workflow_engine_routes.py` — all API endpoints
- `backend/database/workflows.py` — DB access layer

## Full Plan Reference

The canonical 6-phase plan lives at (Cursor internal path — may not be accessible outside the original session):
`/Users/computer/.cursor/plans/generic_workflow_engine_fork_aee1975a.plan.md`

A copy of the plan's key content is inlined in this handoff doc above (architecture, phase summaries). If the plan file is not accessible, this document is self-sufficient.

Summary of remaining phases:

**Phase 3: Expert Steps + Self/Deep Review Templates**
- `ExpertSelectExecutor`, `HolisticReviewExecutor`
- Fan-out/fan-in runtime enhancement
- `expert_domains` and `instance_experts` DB tables
- 10 seeded expert domains
- Expert domain CRUD in Settings UI

**Phase 4: Visual Workflow Designer**
- `reactflow` canvas for drag-and-drop workflow composition
- Step palette, edge drawing, fan-out indicators
- Template validate/save/clone
- `useDesignerStore` Zustand store

**Phase 5: Dashboard + Prioritization UI**
- Review-workflow-aware PR dashboard
- Auto-queue with P0-P3 scoring
- Skip list and code owner registry management
- "Start Workflow" from dashboard rows

**Phase 6: Follow-Up Lifecycle**
- `FollowupCheckExecutor`, `FollowupActionExecutor`
- `review_followups` and `followup_findings` DB tables
- Per-finding resolution tracking
- Re-review on new commits
- Audit trail (terminal states preserved)

## Adversarial Review System Context

This fork integrates the adversarial review workflow defined in a **separate repo** — the `scala` monorepo at `/Users/computer/Work/scala`. The workflow specs live there, not in this repo:

- `/Users/computer/Work/scala/.reviews/workflow-phase1-opus.md` — Phase 1 (triage + prompt generation + Review A)
- `/Users/computer/Work/scala/.reviews/workflow-phase2-chatgpt.md` — Phase 2 (independent Review B)
- `/Users/computer/Work/scala/.reviews/workflow-phase3-opus-synthesis.md` — Phase 3 (synthesis + human gate + publish)
- `/Users/computer/Work/scala/.reviews/workflow-phase4-followup.md` — Phase 4 (follow-up lifecycle)
- `/Users/computer/Work/scala/.reviews/review-process.md` — Full process spec
- `/Users/computer/Work/scala/.reviews/quickstart.md` — Invocation guide
- `/Users/computer/Work/scala/.reviews/prompt-pr-dashboard.md` — PR dashboard prompt

A comprehensive analysis of Jay's original system (pre-fork) is at:
- `/Users/computer/Work/scala/.scratch/gh-pr-explorer-analysis.md`

The workflow engine generalizes these markdown-driven workflows into executable, UI-composable templates. You do NOT need to read those files to continue implementation — the plan file and this handoff doc contain everything needed. Reference them only if you need to verify specific behavioral details (e.g., exact comment formatting rules, Jira integration specifics, follow-up state machine).
