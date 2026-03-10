# Workflow Engine — Knowledge Transfer

> Dense reference for AI agents operating on this codebase. Optimized for rapid context loading.
> Last updated: 2026-03-10.

---

## 1. What This Is

An adversarial code review pipeline ported from a document-based system into a full-stack web app (Flask + React/TypeScript). The core idea: two AI agents independently review a PR, their findings are synthesized, deduplicated, verified for false positives, and optionally published as a GitHub comment.

The system is generic — templates define step graphs, executors implement step logic, and a runtime handles dependency resolution, fan-out parallelism, human gates, and cooperative cancellation.

**Origin**: The workflow engine was grafted onto an existing GitHub PR Explorer app ("Jay's UI"). The PR Explorer handles repo browsing, PR filtering, analytics, merge queue, and single-agent Claude CLI reviews. The workflow engine lives in its own tab ("Review Workflows") and has its own database tables, routes, components, and store — mostly decoupled from the rest of the app.

---

## 2. Architecture At a Glance

```
Template (JSON DAG) → Runtime (topo-sort, level-based parallel exec)
                        ↓
                    StepExecutor.execute(inputs) → StepResult
                        ↓
                    Agent subprocess (Claude/Cursor/OpenAI CLI)
                        ↓
                    SQLite persistence (steps, artifacts, gate payloads)
                        ↓
                    Human Gate (pause → UI review → resume/revise)
                        ↓
                    Publish (gh pr comment)
```

**Key files by layer**:

| Layer | Files |
|-------|-------|
| Runtime | `backend/workflows/runtime.py`, `cancellation.py`, `step_types.py`, `executor.py` |
| Executors (14) | `backend/workflows/executors/*.py` |
| JSON parsing | `backend/workflows/json_parser.py` |
| Agents | `backend/agents/base.py`, `claude_cli.py`, `openai_api.py`, `cursor_cli.py`, `registry.py`, `pid_tracker.py` |
| Database | `backend/database/workflows.py` |
| Routes | `backend/routes/workflow_engine_routes.py` |
| Seed data | `backend/workflows/seed.py` |
| Frontend store | `frontend/src/stores/useWorkflowEngineStore.ts` |
| Frontend API | `frontend/src/api/workflow-engine.ts` |
| Frontend components | `frontend/src/components/engine/*.tsx` |
| Styles | `frontend/src/styles/workflow-engine.css` |

---

## 3. Execution Model

### 3.1 Templates

A template is a JSON DAG of steps. Each step has: `id` (unique string), `type` (from `StepType` enum), `depends_on` (list of step IDs), and optional `config` (agent name, flags).

**Built-in templates** (seeded on startup via `seed.py`):

| Template | Steps | Key Property |
|----------|-------|-------------|
| **Quick Review** | select → prompt → review | Single-agent, no synthesis |
| **Team Review** | select → prioritize → prompt → prompt_gate → [review_a, review_b] → synth → related_scan → fp_check → fresh → gate → pub | Dual-agent adversarial, publishes to GitHub |
| **Self-Review** | select → experts → prompt(per_expert) → prompt_gate → [review_a, review_b] → synth → related_scan → fp_check → holistic → fresh → gate | Multi-expert, local only |
| **Deep Review** | select → experts → prompt(per_expert) → prompt_gate → [review_a, review_b] → synth → related_scan → fp_check → holistic → fresh → gate → pub | Multi-expert + publish |
| **Follow-Up** | check → gate → action | Lightweight re-check cycle |

### 3.2 Runtime (`runtime.py`)

`WorkflowRuntime` resolves the DAG via Kahn's algorithm into dependency levels, then executes each level. Steps within a level run concurrently via `ThreadPoolExecutor`.

**Key methods**:
- `execute(initial_inputs, instance_config)` — full run from start
- `resume_after_gate(gate_step_id, gate_decision, all_outputs, instance_config)` — continue after human approval
- `retry_from_step(retry_step_id, all_outputs, instance_config)` — re-run a failed step and everything downstream

**`_parallel_levels()` algorithm**:
1. Build adjacency list and in-degree map from edges
2. Initialize queue with all steps that have in_degree == 0
3. Iteratively: append sorted(queue) as a level, decrement neighbors, add zero-degree to next queue
4. If visited != len(all_step_ids), raise "contains a cycle"
5. Returns list of levels (each level = list of step IDs that can run concurrently)

**`execute()` flow**:
1. Check all executors exist (missing → `{status: failed, error}`)
2. Get levels via `_parallel_levels()`
3. `step_outputs = {}`, `all_outputs = dict(initial_inputs)`
4. For each level: check cancellation; if 1 step → `_execute_single_step()`, else → `_execute_parallel_steps()`
5. If either returns non-None dict, return immediately (stop workflow)
6. Return `{status: completed, outputs: all_outputs}`

**`_execute_parallel_steps()` flow**:
1. Build per-step inputs (all_outputs + upstream merges)
2. Submit all steps to `ThreadPoolExecutor(max_workers=len(step_ids))`
3. Iterate `as_completed(futures)`: on first failure, set `early_exit`, call `_cancel_sibling_agents()`
4. Mark uncompleted steps as "cancelled"

**`resume_after_gate()` flow**:
1. If gate_decision contains "prompts", overwrite `all_outputs["prompts"]`
2. Merge gate_decision into all_outputs
3. Update gate step to "completed"
4. Reload step_outputs from DB (only completed steps with outputs_json)
5. Skip levels until gate step found, then execute remaining levels

**`retry_from_step()` flow**:
1. Get downstream_inclusive via BFS from retry_step_id
2. Reset all downstream steps to pending (clear outputs, errors)
3. Reload step_outputs from DB (only non-downstream completed steps)
4. Skip levels until retry step found, then execute remaining levels

**Output merging**: All upstream step outputs are merged into a single `inputs` dict for each step. Three keys concatenate lists; all others overwrite (last writer wins):

```python
_MERGEABLE_LIST_KEYS = {"reviews", "findings", "followup_results"}
```

**Gate pause**: When a step returns `StepResult(awaiting_gate=True, gate_payload=...)`, the runtime saves the payload to DB and stops. The UI presents the gate. On approval, `resume_after_gate()` reconstructs `step_outputs` from DB and continues.

### 3.3 Cancellation (`cancellation.py`)

Cooperative — no forced kills of the runtime thread. A central registry tracks:
- `_cancelled_instances: set` — checked by all polling loops every 5s
- `_registered_agents: dict` — live agent handles, terminated on cancel

Functions: `cancel(instance_id)`, `is_cancelled(instance_id)`, `clear(instance_id)`, `register_agent()`, `unregister_agent()`.

`AGENT_POLL_TIMEOUT = 1800` (30 min) prevents infinite hangs on stuck agents.

### 3.4 Fan-Out

Two mechanisms:
1. **Level-based**: Steps at the same dependency level (e.g., review_a and review_b) run in parallel automatically.
2. **Per-domain fan-out**: `agent_review.py` iterates over each prompt (one per domain) sequentially within a single step, dispatching each to the agent. Rerun queue allows retrying individual domains without restarting the step.

### 3.5 JSON Parser (`json_parser.py`)

`extract_json(content: str) → Optional[dict]`:
1. Try fenced code block: `` ```json ... ``` ``
2. Try `json.loads()` on stripped text
3. Fall back to **brace-depth scanning**: tracks depth, in_string, escape — finds outermost `{...}` and parses
4. Returns None if no valid JSON found

This is used by all executors that parse AI agent output.

---

## 4. Step Executors — Data Flow Reference

Every executor inherits `StepExecutor` (`executor.py`) and implements `execute(inputs: dict) -> StepResult`.

```python
@dataclass
class StepResult:
    success: bool
    outputs: dict = field(default_factory=dict)
    artifacts: list = field(default_factory=list)
    error: str | None = None
    awaiting_gate: bool = False
    gate_payload: dict | None = None
```

### 4.1 pr_select

**Reads**: `config.pr_numbers`, `config.mode`
**Writes**: `prs` (list), `owner`, `repo`, `full_repo`, `mode`
**Source**: `backend/workflows/executors/pr_select.py`

Fetches PRs via `gh pr list` or `gh pr view` (for specific numbers). Each PR object includes: number, title, author, additions, deletions, changedFiles, headRefName, headRefOid, baseRefName, body, labels, reviewDecision, url.

### 4.2 prioritize

**Reads**: `prs`
**Writes**: `prs` (batch), `all_scored_prs`, `skipped_prs`, `batch_size`
**Source**: `backend/workflows/executors/prioritize.py`

Scores PRs 0–100 using: size, labels (critical/bug/wip), code owner boost, staleness, reviewDecision. Maps to P0–P3. Preflight auto-skips PRs the authenticated user already reviewed (parallel `gh api` checks via ThreadPoolExecutor). Reads `skip_list` and `code_owner_registry` from DB.

### 4.3 expert_select

**Reads**: `prs`, `mode`
**Writes**: `experts` (list with domain_id, persona, scope, triggers, checklist, anti_patterns, relevance_pct)
**Source**: `backend/workflows/executors/expert_select.py`

For `scala-computing/scala`: static domain matching from DB (10 built-in domains) using `_compute_domain_relevance()` scorer with language exclusion, trigger keywords, title matching, file signals.
For other repos: dispatches an AI agent to generate tailored domains per PR.
Expert count cap: ≤300 LOC→2, ≤800→3, ≤2000→4, >2000→5.

Supports human feedback revision loop: if `human_feedback` contains a `retry_target="experts"` entry, the agent incorporates that feedback.

#### AI Domain Generation Prompt

```
You are selecting expert reviewers for a code review. Analyze the changed files
and diff below, then generate 2-5 expert domains that are ACTUALLY relevant to
this codebase and these changes.

## Changed Files
{file_list}

## Diff Sample (first 3000 lines)
{diff_sample}

## Risk Assessment (evaluate BEFORE selecting experts)
Scan the diff for structural risk signals. When present, include a meta-expert
whose persona and checklist target that specific risk. Meta-experts compete for
the same 2-5 slots as domain experts — prioritize by actual danger over domain
coverage.

Risk signals to look for:
- Heavy branching, complex conditionals, boundary math → Edge Case & Boundary Condition Analyst
- Concurrent, async, threaded code, shared mutable state → Concurrency Safety Reviewer
- Non-trivial algorithms, data structures, perf-critical paths → Algorithm Correctness & Complexity Reviewer
- State machines, workflow transitions, multi-phase orchestration → State Transition Integrity Analyst
- Auth, input validation, trust boundaries, secrets handling → Security Boundary Analyst
- Deep error recovery, retry logic, fallback chains → Failure Mode & Recovery Reviewer

A meta-expert's persona, checklist, and anti_patterns must reference the SPECIFIC
risk patterns found in the diff — not generic boilerplate.

## Rules
- Select 2-5 expert domains based on PR scale (<=300 lines: 2, 301-1500: 3-4, >1500: 4-5)
- Each domain must be relevant to the ACTUAL languages, frameworks, and patterns in the diff
- Do NOT use generic domains like "General" — be specific to what the code actually does
- Think about the DOMAIN PURPOSE of the code, not just the language

## Output — valid JSON only:
{
  "experts": [
    {
      "domain_id": "python-flask-backend",
      "display_name": "Python Flask Backend",
      "persona": "Principal Python backend engineer specializing in Flask... (3-5 sentences)",
      "scope": "Flask routes, database access, error handling, API design",
      "checklist": ["Is error handling consistent across routes?", ...],
      "anti_patterns": ["Bare except clauses swallowing errors", ...]
    }
  ]
}
```

### 4.4 prompt_generate

**Reads**: `prs`, `mode`, `owner`, `repo`, `experts`
**Writes**: `prompts` (list with pr_number, prompt text, domain, head_sha)
**Source**: `backend/workflows/executors/prompt_generate.py`

Two modes:
- `per_expert: true` (self/deep): One prompt per expert per PR. Each prompt has a domain-specific persona, checklist, anti-patterns.
- `per_expert: false` (team): One generic prompt per PR using the dominant expert domain.

#### Full Prompt Structure

The prompt is assembled from these sections in order:

**1. Header**:
```
# Review Prompt: PR #{pr_number} — {title}
Author: {author_login}
Head SHA: {head_sha}
Jira: {jira_str}
Code Owner Reviews: {code_owner_reviews or 'None'}
Generated: {now}
```
With optional suffix for large diffs (>5000 lines):
```
Diff Size: {total} lines (LARGE — use chunked review strategy)
```

**2. Context Commands**:
```
## Context Acquisition Commands
Run ALL of these before analysis:

gh pr view {pr_number} --repo {owner}/{repo} --json body,title,author,labels,headRefName,baseRefName
gh pr diff {pr_number} --repo {owner}/{repo}
gh api repos/{owner}/{repo}/pulls/{pr_number}/comments
gh api repos/{owner}/{repo}/pulls/{pr_number}/reviews
```
For large PRs, adds `--name-only` variant and chunked file review guidance.

**3. Prior Review Deduplication** (fetches existing reviews from DB):
```
## Prior Review Deduplication (mandatory)

After reading existing reviews and comments from the commands above:
- Do NOT restate findings already flagged by other reviewers
- Reference and reinforce findings you agree with if adding meaningful context
- Disagree explicitly if you believe a prior finding is incorrect
- Focus on gaps — what did prior reviewers miss?
```

**4. Persona** (domain-specific or generic):
```
## Persona
Senior software engineer with broad expertise across the full stack. Focus on
code correctness, maintainability, error handling, edge cases, performance, and
security. Be specific and actionable in your findings.
```
Or for expert domains: full persona text from domain definition.

**5. Review Focus** (expert domains only):
```
## Review Focus
{scope from domain definition}
```

**6. Review Checklist** (expert domains only):
```
## Review Checklist
1. {checklist item from domain definition}
2. ...
```

**7. Anti-Patterns** (expert domains only):
```
## Known Anti-Patterns
Watch for these specific patterns in this domain:
- {anti-pattern from domain definition}
```

**8. Cross-Cutting Concerns** (multi-expert only):
```
## Cross-Cutting Concerns
You are the `{expert_display_name}` expert for this PR. Be extra critical within
your domain. Flag cross-cutting concerns you notice outside your domain, but mark
them as `[CROSS-CUTTING — defer to {other-domain} expert]` rather than analyzing
them deeply.
Sibling experts covering other domains: {sibling_list}.
```

**9. Human Feedback** (if revision iteration):
```
## Human Reviewer Guidance
The human reviewer provided this direction (iteration {iteration}):
> {feedback}
Incorporate this guidance into your review focus and priorities.
```

**10. Depth Expectations**:
```
## Depth Expectations
Your review quality is measured by the synthesis phase. Calibration guidelines:
- This is a LARGE PR ({changed_files} files, {total} lines). Expect 5-10+ findings.
  [OR medium: 3+, OR small: proportionate]
- Zero findings + zero questions = re-examine. Even clean PRs deserve questions.
- These are guidelines, not quotas — don't fabricate findings to hit a number.
```

**11. Cross-File Analysis**:
```
## Cross-File Analysis
After reading the diff, perform cross-file analysis. Many real bugs live at boundaries:
- Contract mismatches: Does file A call a function with assumptions file B doesn't satisfy?
- Naming inconsistencies: Same concept named differently across files?
- Incomplete migrations: Pattern changed in some files but not others?
- Initialization order: If file A removes a safety check, does file B guarantee the precondition?
```

**12. Diff Ingestion** (varies by size):

Small (≤5000 lines):
```
## Diff Ingestion
This PR has {total} lines changed. Read the ENTIRE diff — do not sample or skim.
```

Large (>5000 lines):
```
## Diff Ingestion
This PR has {total} lines changed (LARGE). Use a chunked strategy:
1. gh pr diff {pr_number} --name-only to get the complete file list
2. Categorize files: source code, config, tests, docs, generated
3. Read ALL source code and config changes in full
4. Sample test files and generated code for anomalies
5. Document which files you reviewed and which you skipped (with justification)
```

**13. Severity Guide**:
```
## Severity Guide
- Blocking/Critical: Production data loss, security vulnerability, crash in mainline path.
  You MUST describe a concrete production failure scenario — if you cannot, it is NOT blocking.
- Major: Correctness issue with workaround, performance regression, missing error handling
  on external input. Non-blocking by default.
- Minor: Style, naming, documentation, test coverage gap. Never blocking.

Default to non-blocking. When in doubt, mark as major (non-blocking).
```
For large PRs adds: `Cap your total findings at 15-20 max. Group minor issues by category.`

**14. Output Format**:
```
## Output Format
Your review MUST use this exact structure:

# Review: PR #{pr_number} — {title}
## Summary
(2-3 sentence overview)
## Verdict
(APPROVE | CHANGES_REQUESTED | NEEDS_DISCUSSION)
## Blocking Findings
(Numbered. Each: file:line, description, severity, evidence from diff, suggested fix)
## Non-Blocking Findings
(Numbered. Each: file:line, description, suggestion)
## Questions for Author
(Numbered list of clarifying questions)
## Checklist Completion
(Which checklist items were verified, which could not be verified and why)
## Files Reviewed
(List of key files inspected)
```

### 4.5 agent_review

**Reads**: `prompts`
**Writes**: `reviews` (list with pr_number, domain, content_md, content_json, score, phase, agent_name)
**Source**: `backend/workflows/executors/agent_review.py`

Dispatches each prompt to an `AgentBackend` instance. Phase B gets an isolation instruction prepended ("Independent review — do not reference any prior analysis").

Live output tracked via `_agent_domain_store` keyed by `{instance_id}:{step_id}` → `{domain → {status, result, ...}}`. Exposed to frontend via REST endpoint.

Poll loop: 5s interval, 30min timeout, cancellation check each iteration. On completion, extracts `ReviewArtifact` (prefers `.json` file, falls back to `.md`).

Rerun queue: `_rerun_queue` allows retrying individual failed domains from the gate UI without restarting the entire step.

### 4.6 synthesis

**Reads**: `reviews`, `mode`, `prs`
**Writes**: `synthesis` (dict with agreed, a_only, b_only, synthesis_log, questions, verdict, per_domain_synthesis)
**Source**: `backend/workflows/executors/synthesis.py`

**Single-tier** (team-review): Pairs review_a and review_b, matches findings by fuzzy title + file/line overlap. Classifies into agreed/a_only/b_only. Multi-path preservation: when multiple A-findings match the same B-finding, extras go into `additional_failure_modes`.

**Two-tier** (self/deep): Per-domain synthesis first, then aggregation across domains.

**Verdict logic**:
- Both agents agree on critical/major → `CHANGES_REQUESTED`
- Single agent critical → `NEEDS_DISCUSSION`
- Any findings → `COMMENT`
- No findings → `APPROVE`

#### AI Verification Prompt (per-domain, when `ai_verify: true`)

```
You are a senior engineering lead performing SYNTHESIS of two independent code
reviews for the **{domain}** domain.
Agent A: {agent_a_name}
Agent B: {agent_b_name}
Your job: verify every finding against the actual diff, resolve disputes with
evidence, generate SYNTH findings for issues both reviewers missed, and flag
cross-cutting concerns.

## Context Commands (run these to verify findings)
gh pr diff {pr_num} --repo {owner}/{repo}
gh api repos/{owner}/{repo}/pulls/{pr_num}/reviews --paginate
gh api repos/{owner}/{repo}/pulls/{pr_num}/comments --paginate

## Pre-Classified Findings (mechanical)
### {category.upper()} ({count})
{i}. [{severity}] **{title}** at `{loc_str}`
   {problem}

## Review A ({agent_a_name}) — Full Content
{content_md[:8000]}

## Review B ({agent_b_name}) — Full Content
{content_md[:8000]}

## Your Task
For EVERY pre-classified finding:
1. Verify against the actual diff — read the code at the cited location
2. Classify: CONFIRMED | FALSE_POSITIVE | RECLASSIFIED (with new severity)
3. For disputed findings (A_ONLY, B_ONLY): determine validity with code evidence
4. Drop false positives with explicit reasoning
5. Preserve distinct failure modes: If a finding has multiple failure paths,
   each MUST appear as a separate verified_finding. Do NOT collapse multi-path
   findings into a single entry.

Severity calibration:
- A finding is critical/blocking ONLY if you can describe a concrete production
  failure scenario
- If the problem requires unusual conditions or is a best-practice violation,
  it is major at most

Additionally:
- Generate SYNTH findings: issues BOTH reviewers missed (source: 'SYNTH')
- Extract cross-cutting flags: issues outside this domain's scope

## Output — valid JSON only:
{
  "domain": "{domain}",
  "verified_findings": [
    {"title": "...", "severity": "critical|major|minor",
     "classification": "CONFIRMED|FALSE_POSITIVE|RECLASSIFIED",
     "original_category": "AGREED|A_ONLY|B_ONLY",
     "evidence": "...", "source": "review_a|review_b|BOTH"}
  ],
  "synth_findings": [
    {"title": "...", "severity": "...", "description": "...",
     "evidence": "...", "source": "SYNTH"}
  ],
  "cross_cutting_flags": ["description 1", ...],
  "false_positives_dropped": [{"title": "...", "reason": "..."}],
  "synthesis_log": [
    {"finding": "...", "action": "CONFIRMED|DROPPED|RECLASSIFIED", "reasoning": "..."}
  ],
  "domain_verdict": "APPROVE|CHANGES_REQUESTED|NEEDS_DISCUSSION|COMMENT",
  "domain_summary": "2-3 sentence summary for this domain"
}
```

### 4.7 related_issue_scan

**Reads**: `synthesis`, `owner`, `repo`, `prs`
**Writes**: `related_scan` (dict), `synthesis` (deduplicated copy)
**Source**: `backend/workflows/executors/related_issue_scan.py`

Two-phase AI analysis:
1. **Deduplication**: Compares all findings against each other using codebase context. Same file + overlapping lines + same root cause = duplicate. Keeps the more detailed finding, drops the other.
2. **Related issue scan**: For each unique finding, searches the codebase for structurally similar patterns using grep, glob, and file reads.

`_collect_findings()` gathers findings from synthesis and tags each with `_source` (BOTH, A_ONLY, B_ONLY, SYNTH).

`_apply_dedup()` removes dropped findings from synthesis dict, updates counts, adds `dedup_applied` and `dedup_log` metadata. The modified synthesis flows downstream to fp_check and publish.

#### Full Scan Prompt

```
You are a codebase analyst performing a RELATED ISSUE SCAN with DEDUPLICATION.

You have two jobs:

**Job 1 — Deduplication**: Compare all findings against each other to identify
duplicates. Two findings are duplicates when they describe the **same defect**
at the **same code location** (same file, overlapping line ranges). Use the
codebase to verify: read the actual code and confirm whether two findings that
look similar are truly the same bug or distinct issues.
- Word-for-word identical findings at the same location → always a duplicate
- Same file + overlapping lines + same root cause → duplicate even if worded differently
- Same file but different functions/concerns → NOT a duplicate
- Findings at different files that share a root cause → NOT duplicates (report as wider_issues)

**Job 2 — Related Issue Scan**: For each *unique* finding (after dedup), search
the repository for **structurally similar patterns** — not just textual matches.
This means:
- Same error handling approach (e.g., missing error check, swallowed errors)
- Same architectural pattern (e.g., unbounded collect, lock-free shared state)
- Same API usage shape (e.g., unchecked unwrap after fallible call)
- Functionally equivalent code even if variable/function names differ

This determines:
- Whether the 'problem' pattern is actually standard/intentional in the codebase
  (suggesting the finding is a false positive)
- Whether real issues extend beyond the PR diff (wider impact)

Be thorough but efficient. Use grep/search to find actual code, then READ the
surrounding context to confirm structural similarity — don't just count keyword hits.

## Context Commands
gh pr diff {pr_number} --repo {owner}/{repo} --name-only

## Findings to Scan
### Finding {i}: [{severity}] {title}
- Source: {source}
- File: `{file}:{line}`
- Problem: {problem[:300]}

## Your Task

### Step 1 — Deduplication
Compare all findings above against each other:
- For each pair at the **same file** with overlapping line ranges, read the
  actual code to determine if they describe the same defect
- If two are duplicates, keep the one with more detail/better evidence and list
  the other in `duplicates`
- If a finding from A_ONLY or B_ONLY duplicates an AGREED/BOTH finding, the
  AGREED version takes priority
- When merging, note both sources found the issue (increases confidence)

### Step 2 — Related Issue Scan
For each *unique* finding (not dropped as duplicate):
1. Decompose into searchable signals:
   - The specific function/method/API call involved
   - The structural pattern (e.g., 'error return ignored', 'mutex not held across await')
   - The broader category (error handling, resource lifecycle, concurrency)

2. Search using multiple strategies (don't rely on one grep):
   - Grep for the specific function/API name
   - Grep for the structural pattern
   - Glob for files with similar roles (same directory, same suffix)
   - Read surrounding code at matches to verify structural similarity

3. Distinguish textual vs structural matches:
   - Grep hit for same function name = textual — read context for pattern
   - Same error-handling shape in different function = structural match
   - Same variable name but different usage = NOT a match

4. Report with evidence:
   - How many other files have this same structural pattern
   - Whether the pattern appears intentional (comments, tests, consistent usage)
   - If >5 structural instances: likely standard/intentional → probable false positive
   - If 1-3 instances: real issue may be wider than the PR
   - If 0 instances: unique to this PR, finding stands on its own

## Communication Standards
- Be objective and evidence-based — cite file:line for every claim
- Report what you find, not what you assume
- Clearly distinguish 'same keyword' from 'same bug pattern'

## Output — valid JSON only:
{
  "duplicates": [
    {"dropped_title": "...", "kept_title": "...", "file": "...",
     "reason": "Same defect at same location — both describe X"}
  ],
  "scanned_findings": [
    {"title": "...", "pattern_searched": "...", "related_count": 0,
     "pattern_is_standard": false, "related_files": ["..."],
     "assessment": "1-2 sentence explanation"}
  ],
  "likely_false_positives": ["finding title where pattern is standard"],
  "confirmed_findings": ["finding title where pattern is unique/problematic"],
  "wider_issues": [
    {"finding": "title", "additional_files": ["other.rs"], "description": "..."}
  ]
}
```

### 4.8 fp_severity_check

**Reads**: `synthesis`, `related_scan`, `owner`, `repo`, `prs`
**Writes**: `fp_check` (dict with verified_findings, false_positives_removed, severity_changes, final_counts)
**Source**: `backend/workflows/executors/fp_severity_check.py`

Expert verification per finding with three checks:
1. **Correctness**: Trace execution path, check upstream guards, **base-branch verification** for "missing X" claims
2. **Intentionality**: Codebase-wide pattern analysis using related_scan results
3. **Impact**: Concrete production failure scenario required

Preserves `_original_severity` for audit trail. Recalculates verdict from remaining findings.

#### Full Verification Prompt

```
You are a senior engineering lead performing FALSE POSITIVE & SEVERITY verification.

Your job: for each finding from a code review, verify it against the actual code
and determine whether it is real, a false positive, or mis-calibrated in severity.

Key principles:
- Read the actual code — never judge a finding from its description alone
- Trace the full execution path — a function that looks unsafe may be guarded by callers
- Check for upstream invariants — an 'unchecked unwrap' might be guaranteed safe
- Distinguish 'could fail' from 'will fail in production' — theoretical vs practical

You are the last line of defense before findings are published. Be rigorous but fair.

## Context Commands
gh pr diff {pr_num} --repo {owner}/{repo}
gh api repos/{owner}/{repo}/pulls/{pr_num}/files --paginate --jq '.[].filename'

### Base-Branch Verification Commands
Use these to verify 'missing X' claims against the base branch:
# Check if a file/symbol exists on the base branch (before this PR)
gh api repos/{owner}/{repo}/contents/{FILE_PATH}?ref={base_branch} --jq '.name'
# Search for a symbol/attribute on the base branch
gh api -X GET 'search/code?q={SEARCH_TERM}+repo:{owner}/{repo}' --jq '.items[].path'
# View a specific file on the base branch
gh api repos/{owner}/{repo}/contents/{FILE_PATH}?ref={base_branch} --jq '.content' | base64 -d

## Findings to Verify
### Finding {i}: [{severity}] {title}
- Source: {source}
- File: `{file}:{line}`
- Problem: {problem}

## Related Issue Scan Results
**Likely false positives** (pattern is standard in codebase):
- {fp}
For each scanned finding:
- **{title}** {[STANDARD]}: {count} related instances. {assessment}

## Your Task — Three Checks Per Finding

### 1. Correctness Check
Read the code at the cited location. Does it ACTUALLY exhibit the claimed behavior?
- Read the file — do not rely on the finding description alone
- Trace the execution path: follow callers and callees at least one level
- Check whether the problem is real or based on a misreading of the code
- Look for upstream guards (validation, type narrowing, early returns)
- If the file is NEW, verify the finding isn't claiming something was 'changed' or 'removed'
- Check git blame context: is this code new in the PR or pre-existing?

#### MANDATORY: Base-Branch Verification for 'Missing X' Claims
Before confirming ANY finding that claims something is 'missing', 'not defined',
'not present', or 'removed':
1. Search the base branch for the allegedly missing item using commands above
2. If a test references a selector/attribute not in the diff, search the base branch
3. If a finding claims a function/variable is 'not defined', grep the full codebase
4. If a finding claims something was 'removed', verify the file existed before
5. Mark as FALSE_POSITIVE any finding where the 'missing' item exists on the
   base branch and was not removed by this PR

**Checklist** (confirm for each 'missing X' finding):
- [ ] Confirmed X does not exist on the base branch
- [ ] Confirmed X was not imported/defined in a file outside the PR diff
- [ ] If X exists elsewhere, verified this PR actually breaks the reference

### 2. Intentionality Check
Is the pattern used deliberately elsewhere in the codebase?
- Use the related scan results as a starting point
- Check for comments, docs, ADRs, or design decisions
- Pattern used consistently in 5+ files is likely intentional
- Consider language idioms (e.g., `let _ = sender.send()` in Rust is idiomatic)

### 3. Impact Assessment
If this IS a real bug, what is the concrete production impact?
- Describe a specific, realistic scenario where this causes user-visible harm
- 'An attacker could...' requires the input reaching this code path externally
- 'This could panic' requires the panic not being caught by a framework handler
- If you cannot describe a realistic scenario, demote severity
- 'Best practice violation' without production impact = minor at most

## Communication Standards
- Be objective — cite code evidence for every judgment
- Frame demotions constructively
- Never use accusatory language about the original reviewers

## Output — valid JSON only:
{
  "verified_findings": [
    {"title": "...", "original_severity": "critical",
     "calibrated_severity": "major",
     "fp_status": "CONFIRMED|FALSE_POSITIVE|DOWNGRADED|UNCERTAIN",
     "correctness_check": "The code at line 123 does/does not...",
     "base_branch_verified": true,
     "base_branch_note": "Checked base branch: X exists/does not exist at ...",
     "intentionality_check": "Pattern found in N other files...",
     "impact_assessment": "Production scenario: ... / No production impact because...",
     "evidence": "code snippet or reference"}
  ],
  "false_positives_removed": [{"title": "...", "reason": "..."}],
  "severity_changes": [{"title": "...", "from": "critical", "to": "major", "reason": "..."}],
  "final_counts": {"blocking": 0, "non_blocking": 0, "removed": 0}
}
```

### 4.9 holistic_review

**Reads**: `synthesis`, `reviews`, `experts`, `prs`, `owner`, `repo`
**Writes**: `holistic` (dict with _holistic_blocking, _holistic_non_blocking, _cross_cutting, _silent_pass, verdict)
**Source**: `backend/workflows/executors/holistic_review.py`

Tier 2 analysis by a stronger model (default claude-opus). Falls back to heuristic holistic if agent unavailable.

#### Full Holistic Prompt

```
You are a principal engineer with 15+ years of experience performing a HOLISTIC REVIEW.
You have read all per-domain synthesis results. Your job is cross-domain analysis:
finding interactions, contradictions, and gaps that domain experts missed.

## Context for PR #{pr_num}
- `gh pr diff {pr_num}` — full diff
- `gh api repos/{owner}/{repo}/pulls/{pr_num}/reviews --paginate` — reviews

## Expert Domains Analyzed
- **{name}**: {scope}

## Cross-Cutting Flags (Deferred from Tier 1)
You MUST process every cross-cutting flag. Assign each to the correct domain's
findings or elevate as a new holistic finding:
- {flag}

## Per-Domain Synthesis Results
### Domain: {domain}
Verdict: {verdict}
  AGREED: {count} findings
    - [{sev}] {title}
  A_ONLY / B_ONLY: ...

## SYNTH Findings (from Tier 1)
- [{severity}] {title}: {description[:200]}

## Your Task
1. Cross-domain interaction analysis: where changes in one domain affect another
2. Contradiction resolution: where domain experts disagree
3. Severity calibration: blocking ONLY if concrete production failure scenario.
   No minor-to-blocking promotion (severity inflation fix).
4. Gap detection: issues between domain boundaries
5. Silent-pass test detection: check test files for functions that can pass
   without verifying their stated invariant (println/dbg/log instead of assert)
6. Process ALL cross-cutting flags: assign to domain or elevate as holistic
7. Final verdict: APPROVE, REQUEST_CHANGES, or COMMENT

## Communication Standards
- Frame findings as improvements, not accusations
- Never use: careless, sloppy, terrible, obviously wrong, incompetent, lazy
- Severity labels describe code impact, not author competence
- When uncertain, ask a question instead of asserting a bug

## Output — valid JSON only:
{
  "verdict": "APPROVE|REQUEST_CHANGES|COMMENT",
  "blocking_findings": [
    {"title": "...", "severity": "critical|major", "domain": "...",
     "description": "...", "evidence": "..."}
  ],
  "non_blocking_findings": [
    {"title": "...", "severity": "minor|suggestion", "domain": "...",
     "description": "..."}
  ],
  "silent_pass_findings": [
    {"test_name": "...", "file": "...", "line": 0, "issue": "..."}
  ],
  "cross_cutting_findings": [
    {"title": "...", "domains": ["...", "..."], "description": "...",
     "origin": "flag|new"}
  ],
  "domain_verdicts": [{"domain": "...", "verdict": "...", "finding_count": 0}],
  "domain_coverage": ["domain-1", "domain-2"],
  "cross_domain_interactions": [
    {"files": ["..."], "domains": ["..."], "description": "..."}
  ],
  "holistic_analysis_log": [
    {"action": "PROMOTED|DEMOTED|CONFIRMED", "finding": "...", "reasoning": "..."}
  ],
  "summary": "2-3 sentence overall assessment"
}
```

### 4.10 freshness_check

**Reads**: `reviews` or `synthesis`, `holistic`
**Writes**: `freshness` (list with pr_number, classification, per-finding staleness)
**Source**: `backend/workflows/executors/freshness_check.py`

Compares `review_sha` vs current PR `headSha`. Classifications: CURRENT, SUPERSEDED (force-push/rebase), STALE-MAJOR (>5 files changed), STALE-MINOR (1-5 files), UNKNOWN.

#### AI Freshness Prompt (optional, if agent configured)

```
You are a senior code review analyst performing a FRESHNESS CHECK.
A code review was completed, but the PR has changed since then.
Your job: evaluate each review finding against the current PR state.

## PR #{pr_number} ({owner}/{repo})
Staleness classification: **{classification}**
- State: {state}, Author: {author}
- Review decision: {review_decision}, Mergeable: {mergeable}, Labels: {labels}

## Changed Files Since Review ({count} files)
- `{file}`

## New Commits Since Review ({count} commits)
- `{sha[:8]}` ({author}): {message[:200]}

## PR Reviews ({count} reviews)
- **{user}** [{state}] ({submitted_at}): {body_preview}

## PR Comments ({count} comments)
- **{user}** [PR AUTHOR]{type}{path} ({created_at}):
  > {body[:300]}

## Findings to Evaluate ({count} findings)
### Finding {i}: {title}
- Severity: {severity}, Location: {file}
- Problem: {problem[:300]}

## Your Task
For each finding, evaluate:
1. New commits — did the author address this issue?
2. Changed files — was the relevant code modified?
3. Author comments — did the author respond?
4. Other reviewer feedback — confirmed or dismissed?
5. PR state — merged/closed making findings moot?

Classify each: STILL_VALID, RESOLVED, NEEDS_RECHECK, SUPERSEDED

## Output — valid JSON only:
{
  "classification": "CURRENT|STALE-MINOR|STALE-MAJOR|SUPERSEDED",
  "pr_state_summary": "...",
  "finding_assessments": [
    {"title": "...", "status": "STILL_VALID|RESOLVED|NEEDS_RECHECK|SUPERSEDED",
     "justification": "...", "evidence": "..."}
  ],
  "recommendation": "Overall recommendation for the human reviewer"
}
```

### 4.11 human_gate

**Reads**: varies by gate type
**Writes**: `gate_payload` (sets `awaiting_gate=True`)
**Source**: `backend/workflows/executors/human_gate.py`

Two gate types:
- **prompt_review**: Shows generated prompts + expert domains. Gate payload includes: `prompts`, `experts`, `mode`, `expert_source`, `domains_list`, `feedback_history`, `iteration`. User can edit prompts, enable/disable, provide feedback to regenerate experts.
- **review_gate**: Shows full synthesis results. Gate payload includes: `reviews`, `synthesis`, `freshness`, `synthesis_log`, `per_domain_synthesis`, `holistic`, `related_scan`, `fp_check`, `questions`, `checklist_completion`, `finding_staleness`, `followup_results`. User approves to publish or revises.

### 4.12 publish

**Reads**: `synthesis`, `freshness`, `holistic`, `prs`, `owner`, `repo`, `mode`
**Writes**: `published` (list with per-PR status)
**Source**: `backend/workflows/executors/publish.py`

#### GitHub Comment Structure

`build_gh_comment()` assembles sections:

```markdown
## Adversarial Review

{summary or verdict stats}

### Blocking Findings

{i}. **{title}**[{severity}] — `{file_ref}`
   {problem/description}
   Evidence: {evidence}
   **Suggested fix:** {fix}

   (For each additional_failure_mode:)
   {counter}. **{title}**[{severity}] — `{extra_ref}`
      {problem/description}
      **Suggested fix:** {fix}

### Non-Blocking Suggestions

{i}. **{title}**[{severity}] — `{file_ref}`
   {problem/description}

### Cross-Cutting Concerns

{i}. **{title}**({domains})
   {description}

### Silent-Pass Test Warnings

{i}. **{test_name}** — `{file}:{line}`
   {issue}

### Questions

{i}. {question}
(capped at 5; note if more omitted)
```

**Staleness notes** appended if applicable:
- SUPERSEDED: `> **Staleness Warning**: Review generated against commit {sha}. Branch force-pushed/rebased since.`
- STALE-MAJOR: `> **Staleness Note**: Findings may be affected by recent changes: {affected_findings}.`
- STALE-MINOR: `> **Note**: PR has new commits since review. Findings likely still valid.`

**`sanitize_comment()`** strips:
- Issue auto-links: `#123` → `123`
- AI branding patterns: `/as an? (ai|language model|llm|assistant)/i`, `/generated (by|using|with) (ai|claude|gpt)/i`, `/\b(claude|chatgpt|gpt-4)\b(?! (cli|api))/i`

**Publication dedup**: Fetches existing comments, filters already-raised findings before posting.
**Holistic enrichment**: Overlays holistic blocking/non-blocking/cross-cutting/silent-pass findings.
Returns `StepResult(success=False)` on GitHub post failure.

### 4.13 followup_check

**Reads**: `full_repo`, `owner`, `repo`
**Writes**: `followup_results` (list with pr_number, classification, author_responses, findings_status)
**Source**: `backend/workflows/executors/followup_check.py`

Deterministic classification (no AI prompt):

```python
def _classify(fu, has_new_commits, author_responses, new_comment_count, findings):
    if not has_new_commits and not author_responses and new_comment_count == 0:
        return "NO_RESPONSE"
    if author_responses:
        response_texts = " ".join(r.get("body", "").lower() for r in author_responses)
        if any(kw in response_texts for kw in ["disagree", "won't fix", "by design", "intentional"]):
            return "AUTHOR_DISAGREES"
        if has_new_commits:
            all_open = [f for f in findings if f.get("status") in ("OPEN", None)]
            return "RESOLVED" if not all_open else "PARTIALLY_RESOLVED"
        return "DISCUSSING"
    if has_new_commits:
        return "PARTIALLY_RESOLVED"
    return current_status
```

### 4.14 followup_action

**Reads**: `followup_results`, `owner`, `repo`
**Writes**: `actions_taken` (list with pr_number, action, classification)
**Source**: `backend/workflows/executors/followup_action.py`

#### Comment Templates

```python
TEMPLATES = {
    "RESOLVED": (
        "Thanks {author} — all blocking items have been resolved. "
        "The adversarial review is satisfied.\n\n{note}"
    ),
    "PARTIALLY_RESOLVED": (
        "Thanks for the updates. {resolved_count} of {total_count} blocking items resolved.\n\n"
        "### Still Open\n\n{open_items}\n\n"
        "### Resolved\n\n{resolved_items}"
    ),
    "AUTHOR_DISAGREES": (
        "Noted — the author disagrees with the following finding(s):\n\n"
        "{disagreed_items}\n\n"
        "The review team will evaluate and respond."
    ),
    "NO_RESPONSE": (
        "Friendly follow-up: the adversarial review posted on this PR has "
        "{total_count} blocking finding(s) that have not yet been addressed.\n\n"
        "### Outstanding Items\n\n{open_items}"
    ),
}
```

All comments pass through `sanitize_comment()`.

---

## 5. Agent Subsystem

### 5.1 Core Types (`base.py`)

```python
class AgentStatus(Enum):
    PENDING, RUNNING, COMPLETED, FAILED, CANCELLED

@dataclass
class AgentHandle:
    agent_name: str
    handle_id: str
    metadata: dict = field(default_factory=dict)

@dataclass
class ReviewArtifact:
    content_md: str | None = None
    content_json: dict | None = None
    file_path: str | None = None
    score: float | None = None
    error: str | None = None
    usage: dict | None = None
    # usage keys: input_tokens, output_tokens, cache_read_input_tokens,
    #   cache_creation_input_tokens, cost_usd, duration_ms, num_turns

class AgentBackend(ABC):
    def start_review(prompt, context) → AgentHandle     # abstract
    def check_status(handle) → AgentStatus              # abstract
    def get_output(handle) → ReviewArtifact             # abstract
    def get_live_output(handle) → str                   # optional, default ""
    def cancel(handle) → bool                           # optional, default False
    def cleanup(handle) → None                          # optional, no-op
```

`normalize_usage(raw)` converts camelCase (from Cursor) to snake_case: `inputTokens → input_tokens`, etc.

### 5.2 Claude CLI Agent (`claude_cli.py`)

**Subprocess command**:
```python
cmd = [
    "claude", "-p", full_prompt,
    "--output-format", "stream-json",
    "--verbose",
    "--allowedTools", _ALLOWED_TOOLS,
    "--dangerously-skip-permissions",
]
if self.model: cmd.extend(["--model", self.model])
if self.effort: cmd.extend(["--effort", self.effort])
```

**Allowed tools**:
```
Bash(git status*),Bash(git log*),Bash(git show*),Bash(git diff*),
Bash(git blame*),Bash(git branch*),Bash(gh pr view*),Bash(gh pr diff*),
Bash(gh pr checks*),Bash(gh api*),Read,Glob,Grep,Write,Task
```

**Schema instructions** (injected into prompt for JSON output):
```
The JSON must have these top-level keys:
"schema_version" (set to "1.0.0"),
"metadata" (object with pr_number, repository, pr_url, pr_title, author,
  branch {head, base}, review_date, review_type, files_changed, additions, deletions),
"summary" (string),
"sections" (array of objects with type=critical|major|minor, display_name,
  and issues array),
"highlights" (array of strings),
"recommendations" (array of {priority: must_fix|high|medium|low, text}),
"score" (object with overall 0-10, optional breakdown array of
  {category, score, comment}, optional summary).
Each issue MUST have: title, location {file, start_line, end_line},
  problem, and optionally fix and code_snippet.
```

**Non-interactive instruction** (appended to non-review prompts):
```
CRITICAL: You are running in a fully automated, non-interactive pipeline.
NEVER ask the user questions, request clarification, or wait for input.
Make your own best-judgment decisions and continue autonomously.
```

**Review file path**: `{reviews_dir}/run-{instance_id}/{owner}-{repo}-pr-{number}{-review-{phase}}{-{domain}}.md`

**Stream-JSON parsing** (`_ProcessState._read_stream_json()`):
- Reads stdout line-by-line on daemon thread
- For `type == "assistant"` messages: extracts text content blocks, appends `[Using tool: {name}]` for tool_use blocks
- Uses prefix-match delta algorithm: compares cumulative `_last_full` with new text to extract only new content
- For `type == "result"`: captures `_result_text`, `_usage`, `_cost_usd`, `_duration_ms`, `_num_turns`
- Keeps last 300 of 500 `_live_lines` for memory efficiency

**`get_output()`**:
1. Read `.json` file if exists, validate via `validate_review_json()`
2. Fall back to `markdown_to_json()` from `.md` content
3. Fall back to `get_live_text()` or raw stdout
4. Extract score from `content_json["score"]["overall"]`
5. Build usage dict from stream-json result metadata

**`cancel()`**: Kills process group via `os.killpg(os.getpgid(pid), SIGTERM)`, escalates to SIGKILL.

### 5.3 Cursor CLI Agent (`cursor_cli.py`)

Similar to Claude CLI but uses `agent` binary with `--print --trust --force --output-format stream-json --stream-partial-output`. Config options: `model`, `sandbox` (default "disabled"), `mode` (agent/plan/ask). Phase B uses separate `--workspace` directory.

### 5.4 OpenAI Agent (`openai_api.py`)

No subprocess. Spawns daemon thread calling `httpx.post("https://api.openai.com/v1/chat/completions")`. System message: "You are an elite code reviewer." User message includes prompt + PR diff (truncated to 50K chars). Parameters: `max_tokens=8000`, `temperature=0.3`, `timeout=300`.

### 5.5 Built-in Agents (11)

| Name | Type | Model | Effort |
|------|------|-------|--------|
| `claude-opus` | claude_cli | opus | — |
| `claude-opus-low` | claude_cli | opus | low |
| `claude-opus-max` | claude_cli | opus | max |
| `claude-sonnet` | claude_cli | sonnet | — |
| `claude-sonnet-low` | claude_cli | sonnet | low |
| `claude-sonnet-max` | claude_cli | sonnet | max |
| `claude-haiku` | claude_cli | haiku | — |
| `claude-haiku-low` | claude_cli | haiku | low |
| `cursor-opus-thinking` | cursor_cli | opus-thinking | — |
| `cursor-codex-high` | cursor_cli | codex | high |
| `cursor-codex-xhigh` | cursor_cli | codex | xhigh |
| `openai-gpt4o` | openai_api | gpt-4o | — |

### 5.6 Registry (`registry.py`)

`get_agent(name, agent_config=None)`: checks instance cache → config.json agents → DB lookup (is_active=True). Caches instances. Raises `ValueError` if unknown.

`list_agents()`: Returns list from config.json. Fallback: `[{"name": "claude", "type": "claude_cli", "model": "opus"}]`.

### 5.7 PID Tracking (`pid_tracker.py`)

`register_pid(pid, *, instance_id, step_id, agent_name, domain)` → INSERT into `active_agent_pids`.
`unregister_pid(pid)` → DELETE.
`kill_all_tracked() → int` → SIGTERM all tracked PIDs, clear table. Called on server startup.

---

## 6. Database Schema

**Source**: `backend/database/workflows.py`

SQLite with WAL journal mode and 5s busy_timeout for safe concurrent access.

### 6.1 Tables

```sql
CREATE TABLE workflow_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    description TEXT,
    template_json TEXT NOT NULL,
    is_builtin BOOLEAN DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE workflow_instances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    template_id INTEGER REFERENCES workflow_templates(id),
    repo TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    config_json TEXT,
    usage_json TEXT,
    pr_count INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE instance_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id INTEGER REFERENCES workflow_instances(id),
    step_id TEXT NOT NULL,
    step_type TEXT NOT NULL,
    step_config_json TEXT,
    status TEXT DEFAULT 'pending',
    agent_id INTEGER REFERENCES agents(id),
    inputs_json TEXT,
    outputs_json TEXT,
    started_at DATETIME,
    completed_at DATETIME,
    error_message TEXT
);

CREATE TABLE instance_artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id INTEGER REFERENCES workflow_instances(id),
    step_id TEXT NOT NULL,
    pr_number INTEGER,
    artifact_type TEXT,
    file_path TEXT,
    content_json TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    type TEXT NOT NULL,
    model TEXT,
    config_json TEXT,
    is_active BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE expert_domains (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain_id TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    persona TEXT,
    scope TEXT,
    triggers_json TEXT,
    checklist_json TEXT,
    anti_patterns_json TEXT,
    is_builtin BOOLEAN DEFAULT 0,
    is_active BOOLEAN DEFAULT 1,
    repo TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE code_owner_registry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    github_handle TEXT UNIQUE NOT NULL,
    display_name TEXT,
    priority_boost INTEGER DEFAULT 0,
    is_reviewer BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE skip_list (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pr_number INTEGER NOT NULL,
    repo TEXT NOT NULL,
    reason TEXT,
    skipped_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    instance_id INTEGER,
    UNIQUE(pr_number, repo)
);

CREATE TABLE review_followups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id INTEGER,
    pr_number INTEGER NOT NULL,
    repo TEXT NOT NULL,
    source_run_id INTEGER REFERENCES workflow_instances(id) ON DELETE CASCADE,
    verdict TEXT,
    review_sha TEXT,
    status TEXT DEFAULT 'NO_RESPONSE',
    published_at DATETIME,
    last_checked DATETIME,
    notes TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE followup_findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    followup_id INTEGER REFERENCES review_followups(id) ON DELETE CASCADE,
    finding_id TEXT NOT NULL,
    original_text TEXT,
    severity TEXT,
    status TEXT DEFAULT 'OPEN',
    author_response TEXT,
    resolution_notes TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE active_agent_pids (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id INTEGER,
    step_id TEXT,
    pid INTEGER NOT NULL UNIQUE,
    agent_name TEXT,
    domain TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 6.2 Status Values

Instance: `pending`, `running`, `completed`, `failed`, `cancelled`, `awaiting_gate`.
Step: `pending`, `running`, `completed`, `failed`, `cancelled`, `awaiting_gate`, `skipped`.

### 6.3 Key DB Methods

**Templates**: `list_templates()`, `get_template(id)`, `get_template_by_name(name)`, `create_template()`, `update_template()`, `delete_template()`.

**Instances**: `create_instance()`, `get_instance()` (with template_name, parsed config), `list_instances(repo?)`, `update_instance_status()`, `update_instance_config()`, `save_instance_usage(instance_id, usage, pr_count)`.

**Steps**: `create_step()`, `update_step_status()` (sets started_at on "running", completed_at on terminal), `get_steps()`, `save_step_outputs()`, `save_gate_payload()`, `reset_steps(instance_id, step_ids)` (clears outputs/errors, deletes artifacts).

**Artifacts**: `save_artifact()`, `get_artifacts(instance_id, step_id?)`.

**Agents**: `list_agents()`, `get_agent()`, `create_agent()`, `upsert_agent()`.

**Expert Domains**: `list_expert_domains(active_only, repo?)`, `get_expert_domain()`, `create_expert_domain()`, `upsert_expert_domain()`, `update_expert_domain(domain_id, **kwargs)`, `delete_expert_domain()`, `insert_ai_expert_domains(repo, experts)`.

**Follow-ups**: `create_followup()`, `get_followup()`, `list_followups(repo?, status?)`, `update_followup_status()`, `create_followup_finding()`, `update_followup_finding()`, `get_followup_findings()`.

**Usage**: `get_usage_stats()` → aggregates by template_name: run_count, total_prs, avg tokens/cost per run and per PR.

---

## 7. REST API

**Source**: `backend/routes/workflow_engine_routes.py`

### Templates
| Method | Endpoint | Notes |
|--------|----------|-------|
| GET | `/api/templates` | List all (builtin first) |
| GET | `/api/templates/<id>` | Includes parsed `template` object |
| POST | `/api/templates` | `{name, description?, template}` |
| PUT | `/api/templates/<id>` | Non-builtin only |
| DELETE | `/api/templates/<id>` | Non-builtin only |
| POST | `/api/templates/<id>/clone` | `{name?}` |
| POST | `/api/templates/<id>/validate` | Returns `{valid, errors[]}` |

### Instances
| Method | Endpoint | Notes |
|--------|----------|-------|
| POST | `/api/workflows/run` | `{template_id, repo, config?}` → spawns background thread |
| GET | `/api/workflows/instances` | `?repo=owner/repo` filter |
| GET | `/api/workflows/instances/<id>` | Includes steps + artifacts |
| POST | `/api/workflows/instances/<id>/gate` | `{action: approve|reject|revise, ...data}` — per-instance mutex |
| DELETE | `/api/workflows/instances/<id>` | Signals cancellation to running agents |

### Steps
| Method | Endpoint | Notes |
|--------|----------|-------|
| GET | `/api/workflows/instances/<id>/steps/<step_id>/live` | Live agent output text |
| POST | `/api/workflows/instances/<id>/steps/<step_id>/retry` | Resets step + downstream, merges prior outputs |
| POST | `/api/workflows/instances/<id>/steps/<step_id>/agents/<domain>/cancel` | Cancel one domain |
| POST | `/api/workflows/instances/<id>/steps/<step_id>/agents/<domain>/rerun` | Requeue failed domain |

### Other
| Method | Endpoint | Notes |
|--------|----------|-------|
| GET | `/api/agents` | List from config.json |
| GET | `/api/step-types` | Registered step types |
| GET/POST/PUT/DELETE | `/api/expert-domains[/<id>]` | Domain CRUD |
| GET | `/api/followups[/<id>]` | `?repo=&status=` filters |
| GET | `/api/workflows/usage-stats` | Token/cost aggregates per template |
| GET/DELETE | `/api/workflows/instances/<id>/feedback` | Human feedback history |

### Background Execution

Route handlers spawn `threading.Thread` for `_run_workflow()`, `_resume_workflow()`, `_retry_from_step()`. `_set_terminal_status()` never overwrites `cancelled` status. `_persist_usage()` aggregates token counts from step outputs.

Per-instance locks (`_gate_locks`, `_instance_locks`) prevent duplicate concurrent operations.

---

## 8. Frontend Architecture

### 8.1 View Routing

`WorkflowEngineView.tsx` manages a `view` state: `list` | `config` | `detail` | `gate` | `domains` | `followups`. Each maps to a component.

### 8.2 Components

#### WorkflowRunList (`WorkflowRunList.tsx`)

Instance table with status filter bar (all/running/waiting/completed/failed with live counts). Buttons: "+ New Run", "Expert Domains", "Follow-Ups". Auto-polls every 5s when active runs exist. Includes collapsible `UsageStatsPanel` showing token/cost breakdown by template (avg per run, avg per PR).

#### RunConfigPanel (`RunConfigPanel.tsx`)

Template selection via card grid with badges (Built-in, Not Available). Disabled when required step types missing. PR selection: radio "All open PRs" vs "Specific PRs" (comma-separated input). Batch size control for prioritize step. Pipeline preview: numbered step list. Agent assignment: "Set All" dropdown for bulk + per-step individual selects showing agent name, model, effort badge.

Config building:
```typescript
config = {
  agent_overrides: { [step_id]: agent_name },  // if any overrides
  step_overrides: {
    [select_step_id]: { pr_numbers: [1, 2, 3] },  // if specific PRs
    [prioritize_step_id]: { max_batch: N },         // if batch != 10
  }
}
```

#### WorkflowRunDetail (`WorkflowRunDetail.tsx`)

Two-panel layout (280px left + 1fr right). Auto-polls every 3s when running/awaiting_gate.

**Left panel — Step Timeline**: Vertical step list with status indicator dots (colored per status), pulse animation on running/awaiting_gate, step type icon + label, status badge, step_id, per-step token count with tooltip, duration. Active step highlighted with left border glow.

**Right panel — Content Viewer**: Header with icon, step type, status badge. Download buttons (.md, .json) for completed steps. Retry button with stale feedback indicator (fetches feedback via `getInstanceFeedback()`, shows badge + tooltip if feedback exists for this step). Progress bar with "X / Y steps" and percentage.

**Auto-advance**: When selected step transitions from `running` to `completed`/`failed`, auto-selects next running step.

**Token usage aggregation**: Iterates all steps, accumulates input/output/cache tokens, cost, turns, duration. Displayed in run header via `TokenUsageBreakdown`.

#### StepContentViewer (`StepContentViewer.tsx`)

Dispatches to type-specific renderers via `VIEWERS` map. Output wrapper keys unwrapped before rendering:
```typescript
const WRAPPER_KEYS = {
  synthesis: 'synthesis',
  holistic_review: 'holistic',
  related_issue_scan: 'related_scan',
  fp_severity_check: 'fp_check',
}
```

**PRSelectView**: PR list with number links, title, author.

**PrioritizeView**: Priority badges (P0-P3, color-coded), scores, rationale, skipped PRs section.

**PromptView**: Collapsible prompts per PR. Parses prompt into sections via `## ` header splitting. Each section independently collapsible with `▼/▶` toggle. Domain badge per prompt.

**ReviewView**: Handles single review (verdict + summary + findings) and multi-domain review list (`DomainReviewList` with per-domain collapsible headers showing status, domain, score, agent name).

**SynthesisView**: Verdict badge (APPROVE/CHANGES_REQUESTED/NEEDS_DISCUSSION), agreement rate, classification grid (Agreed/A-Only/B-Only sections with `FindingCard` components), synth findings, cross-cutting flags, false positives dropped, questions, per-domain synthesis, collapsible synthesis log with action badges (CONFIRMED/DROPPED/RECLASSIFIED).

**RelatedIssueScanView**: Badge row (scanned count, duplicates removed, likely FP, confirmed, wider issues). Collapsible "Duplicates Removed" section with dropped/kept titles, file, reason. Scanned findings with pattern, related count, STANDARD badge, assessment. Wider issues section.

**FPSeverityCheckView**: Final counts badges (blocking/non-blocking/removed/severity changed). False positives removed section. Severity changes section (from → to badges). Verified findings with FP status badge, calibrated severity, original severity strikethrough, correctness/intentionality/impact check text, base-branch verification badge (Verified/Not Verified with note).

**HolisticView**: Uses `SynthesisView`-compatible structure.

**FreshnessView**: Per-PR freshness cards with classification, SHA comparison, affected findings.

**Live output**: Polls `getStepLiveOutput()` for running steps, displays streaming markdown.

**Token utilities**: `TokenUsageBadge` (compact inline), `TokenUsageBreakdown` (expanded grid with input/output/cache/turns/duration/cost), `formatTokenCount()` (1.5K, 2.3M formatting).

#### GateView (`GateView.tsx`)

Full-page gate with two modes:

**PromptReviewGate** (for `gate_type === 'prompt_review'`):
- Editable prompts with enable/disable checkboxes per prompt
- Expandable prompt textarea
- Stats: total prompts, enabled count, expert domains, mode, expert source badge
- Actions: "Approve & Run Agents" (sends enabled/edited prompts), "Revise" (regenerates experts with feedback), "Cancel Workflow"
- Feedback history from previous iterations

**Regular Gate** (10 tabs):
1. **Overview**: Holistic summary, blocking/non-blocking/cross-cutting findings, agreed/A-only/B-only
2. **Comparison**: Per-domain side-by-side Agent A vs B with synthesis classification
3. **Reviews**: Per-domain expandable review markdown
4. **Publish**: Preview of final GitHub comment (via `PublishPreviewFromGate`)
5. **Freshness**: PR freshness cards with SHAs and affected findings
6. **Synthesis Log**: Entries with action badges (CONFIRMED/DROPPED/PROMOTED/DEMOTED)
7. **Questions**: Ordered list of reviewer questions
8. **Domains**: Per-domain cards with verdict badges
9. **Related Scan**: Likely FPs, confirmed findings, wider issues, scanned findings
10. **FP Check**: False positives removed, severity changes, verified findings

Actions: Approve, Revise (with feedback textarea), Cancel.

#### FindingCard (`FindingCard.tsx`)

Severity badge (critical→error, major→warning, minor→neutral), title, classification badge (AGREED/A-ONLY/B-ONLY), source badge (A/B/BOTH), file:line location, problem paragraph, fix recommendation box.

#### ReviewComparison (`ReviewComparison.tsx`)

Two-column grid: Agent A | Agent B. Each column: agent label + verdict badge, summary, finding cards. Below: synthesis classification sections (Agreed, A-Only, B-Only).

#### PublishPreview (`PublishPreview.tsx`)

Searches artifacts for publish/comment type. Falls back to reconstruction from synthesis data. Displays final markdown in preformatted block.

#### ExpertDomainManager (`ExpertDomainManager.tsx`)

Collapsible domain list. Each domain: display name, domain_id, built-in badge, active/disabled status, checklist count, anti-patterns count. Expanded: persona, scope, triggers (file patterns + keywords as code badges), checklist, anti-patterns. Actions: enable/disable, delete (non-builtin only). Create form with domain_id, display_name, persona, scope inputs.

#### FollowUpTracker (`FollowUpTracker.tsx`)

Follow-up list with collapsible items. Header: PR number, repo, status badge (NO_RESPONSE/DISCUSSING/PARTIALLY_RESOLVED/etc.), verdict badge, published date. Expanded: source run ID, review SHA (first 8 chars), last checked, notes, findings table (per-finding status badge, severity badge, original text, author response).

### 8.3 Zustand Store (`useWorkflowEngineStore.ts`)

```typescript
interface WorkflowEngineState {
  templates: WorkflowTemplate[]
  instances: WorkflowInstance[]
  agents: Agent[]
  selectedInstance: WorkflowInstance | null
  loading: boolean           // template fetch
  loadingInstances: boolean
  loadingInstance: boolean   // single instance fetch
  submitting: boolean        // gate actions
  error: string | null
}
```

Actions: `fetchTemplates()`, `fetchInstances(repo?)`, `fetchInstance(id)`, `fetchAgents()`, `startRun(templateId, repo, config?)`, `approveGate(instanceId, data?)`, `rejectGate(instanceId, data?)`, `reviseGate(instanceId, feedback)`, `cancelRun(instanceId)`, `clearError()`.

### 8.4 API Client (`workflow-engine.ts`)

Key types: `WorkflowTemplate`, `WorkflowInstance`, `WorkflowStep`, `WorkflowArtifact`, `Agent`, `ExpertDomain`, `ReviewFollowup`, `FollowupFinding`, `AgentDomainInfo`, `TemplateUsageStats`.

Key functions: `listTemplates()`, `getTemplate()`, `listInstances()`, `getInstance()`, `runWorkflow()`, `gateAction()`, `cancelInstance()`, `listAgents()`, `getAvailableStepTypes()`, `getAgentDomains()`, `cancelAgentDomain()`, `rerunAgentDomain()`, `getStepLiveOutput()`, `retryStep()`, `getInstanceFeedback()`, `clearInstanceFeedback()`, `listExpertDomains()`, `createExpertDomain()`, `updateExpertDomain()`, `deleteExpertDomain()`, `listFollowups()`, `getFollowup()`, `getUsageStats()`.

Utilities: `parseContent(raw)`, `getStepDownloadUrl(instanceId, stepId, format)`, `formatTokenCount(n)`.

### 8.5 CSS Architecture (`workflow-engine.css`)

Namespace: `mx-` prefix. Layout: flex columns primary, CSS grid for templates/panels. Two-panel detail: `280px | 1fr`. Responsive at 768px → single column.

Status colors via `mx-badge` variants: `success` (green), `error` (red), `warning` (yellow), `info` (blue), `neutral` (gray). Animations: `@keyframes mx-step-pulse` for running steps, width transition on progress bar.

Key class hierarchy:
- `.mx-engine-list` → `.mx-engine-list__filters` → `.mx-engine-list__filter`
- `.mx-run-config` → `.mx-run-config__templates` → `.mx-run-config__tpl-card`
- `.mx-run-detail` → `.mx-run-detail__panels` → `.mx-run-detail__timeline` + `.mx-run-detail__content`
- `.mx-step-content` → type-specific containers
- `.mx-gate-view` → `.mx-gate-view__tabs` → `.mx-gate-view__body`
- `.mx-finding` → `.mx-finding__header` + `.mx-finding__location` + `.mx-finding__problem` + `.mx-finding__fix`

---

## 9. Data Flow — Team Review (Canonical Path)

```
pr_select
  → prs[], owner, repo, full_repo, mode
     ↓
prioritize
  → prs[] (batched, scored), skipped_prs
     ↓
prompt_generate
  → prompts[] (one per PR, with dominant domain)
     ↓
human_gate (prompt_review)
  ← PAUSED — user reviews prompts, edits, approves
     ↓
agent_review (phase=a)  ║  agent_review (phase=b)     [parallel]
  → reviews[] (phase a)  ║  → reviews[] (phase b)
     ↓ (merged into single reviews list via _MERGEABLE_LIST_KEYS)
synthesis
  → synthesis{agreed, a_only, b_only, verdict, synthesis_log, questions}
     ↓
related_issue_scan
  → related_scan{duplicates, scanned_findings, likely_false_positives,
                  confirmed_findings, wider_issues}
  → synthesis (deduplicated — duplicates removed, counts updated)
     ↓
fp_severity_check
  → fp_check{verified_findings, false_positives_removed, severity_changes, final_counts}
     ↓
freshness_check
  → freshness[{pr_number, classification, finding_staleness}]
     ↓
human_gate (review_gate)
  ← PAUSED — user reviews synthesis, approves/revises
     ↓
publish
  → published[{pr_number, status, comment_url}]
```

---

## 10. Expert Domain System

### 10.1 Built-in Domains (10)

| Domain ID | Persona Summary | Triggers |
|-----------|----------------|----------|
| `rust-api` | Principal Rust engineer — Axum/Tower, typed extractors, error handling, HTTP semantics, serde | Files: `routes/*.rs`, `server/*.rs`. Keywords: `axum::`, `StatusCode`, `handler`, `into_response` |
| `database` | Principal database engineer — PostgreSQL, SQLx, transaction isolation, migrations, N+1 | Files: `models/*.rs`, `migrations/`, `*.sql`. Keywords: `sqlx::`, `BEGIN`, `COMMIT`, `transaction` |
| `s3-cloud` | Principal cloud infrastructure — S3 multipart lifecycle, presigned URLs, CAS, consistency | Keywords: `s3_client`, `multipart`, `presign`, `upload_id` |
| `concurrency` | Principal systems engineer — state machines, OCC, tokio, cancellation safety, Send/Sync | Keywords: `Mutex`, `RwLock`, `atomic`, `CancellationToken`, `OCC` |
| `security` | Principal AppSec — OWASP Top 10, path traversal, injection, auth/authz, secrets, CORS | Files: `auth[_/]`, `middleware/`. Keywords: `validate_`, `sanitize`, `CORS`, `RBAC` |
| `testing` | Principal QA/test architect — test pyramid, assertion quality, edge cases, coverage | Files: `tests/`, `#[test]`. Keywords: `assert`, `mock`, `fixture` |
| `infra-ci` | Principal DevSecOps — Docker, GitHub Actions, IaC, IAM, supply chain | Files: `Dockerfile`, `.github/`, `justfile`, `*.tf`. Keywords: `pipeline`, `deploy`, `CI/CD` |
| `go-backend` | Principal Go engineer — goroutine lifecycle, context propagation, interface design | Files: `*.go`, `go.mod`. Keywords: `goroutine`, `chan`, `sync.` |
| `cpp-simulator` | Principal C++ engineer — NS3, RAII, congestion control, simulation correctness | Files: `*.cc`, `*.cpp`, `*.h`. Keywords: `ns3::`, `Simulator::`, `congestion` |
| `python-tooling` | Principal Python toolchain — dependency management, supply chain, script correctness | Files: `*.py`, `requirements.txt`, `pyproject.toml`. Keywords: `pip` |

Each domain has 5-7 checklist items and 3-4 anti-patterns. See `seed.py` for full persona text.

### 10.2 Static Scoring Algorithm (`expert_select.py`)

Used for `scala-computing/scala` repo. `_compute_domain_relevance()` scorer:

1. **Language exclusion** (hard gate): cpp-simulator excluded from Rust-only PRs, etc.
2. **Language match bonus**: 1.4x multiplier when domain's language matches file languages
3. **Identity keywords**: Extracted from domain name + scope, matched against files + diff
4. **Trigger keywords**: Domain-specific high-signal terms scored independently (not diluted by identity count)
5. **Title matching**: PR title keywords weighted 8x (identity), 12x (trigger)
6. **File signal detection**: Language/framework from extensions (`_EXT_TO_LANG`), directory names (`_DIR_SIGNALS`), Python-specific basenames
7. **Minimum threshold**: 15.0 (domains below excluded)
8. **Expert count cap**: ≤300 LOC→2, ≤800→3, ≤2000→4, >2000→5

---

## 11. Key Design Decisions & Gotchas

1. **Output merging is last-writer-wins** except for `reviews`, `findings`, `followup_results`. If two steps write the same key, the later one silently overwrites. This is intentional — e.g., `related_issue_scan` overwrites `synthesis` with the deduplicated version.

2. **Gate payloads are snapshots**. The gate payload saved to DB captures the state at gate time. If you retry an upstream step, the old gate payload becomes stale — the runtime reconstructs from DB on resume.

3. **Agent handles are opaque**. Different backends use different handle internals (subprocess PID, request ID, etc). The executor only sees `AgentHandle` with `handle_id` and `metadata`.

4. **Per-instance mutex on gate actions**. `_gate_locks` and `_instance_locks` prevent race conditions from double-clicking approve or concurrent retry/resume operations.

5. **`_set_terminal_status()` never overwrites `cancelled`**. This prevents background threads from setting `completed` or `failed` after the user has already cancelled.

6. **Review file naming encodes context**: `run-{instance_id}/{owner}-{repo}-pr-{number}-review-{phase}-{domain}.md`. Phase is `a` or `b`. Domain is the expert domain slug. Follow-ups get `-followup-{timestamp}` suffix.

7. **Synthesis loss prevention**: `additional_failure_modes` preserves multiple A-findings that match the same B-finding. Without this, synthesis would silently drop all but one match.

8. **Single-agent critical → NEEDS_DISCUSSION, not CHANGES_REQUESTED**. Only when both agents independently find a critical issue does the verdict escalate. This reduces false blocking.

9. **Base-branch verification is prompt-based, not code-based**. The FP check *instructs* the AI agent to verify against the base branch using `gh api` commands. There's no programmatic verification — it relies on the agent following instructions.

10. **Dedup is AI-powered, not mechanical**. The related issue scan agent decides whether two findings are duplicates by reading the actual code, not just comparing titles/lines mechanically. This means dedup quality depends on the agent's judgment.

11. **The workflow engine is mostly independent from the rest of the app**. It shares: Flask app factory, SQLite database file, config loading, `gh` CLI wrapper. It does NOT share: the single-agent review system (`review_service.py`), the in-memory cache, or the Zustand PR/analytics stores.

12. **`extract_json()` brace-depth scanner** handles AI output that wraps JSON in markdown, extra text, or incomplete fences. The scanner tracks string escaping and nesting depth to find the outermost `{...}` block.

13. **Retry preserves upstream context**. `retry_from_step()` resets the target + all downstream steps, then reconstructs `step_outputs` from DB (only non-reset completed steps). This ensures the retried step receives correct inputs even if earlier steps produced different outputs.

14. **Live output is delta-based**. Claude CLI stream-json parsing uses a prefix-match algorithm: compares cumulative text against previous snapshot to extract only new content for the frontend, keeping memory bounded (last 300 lines).

---

## 12. Configuration

**`config.json`** agents section defines available agents with type + model + effort level.

**`seed.py`** runs on startup: upserts built-in templates, agents, and expert domains. Idempotent.

**Instance `config_json`** (per-run): stores agent overrides per step, PR numbers, batch size, mode, and accumulated human feedback from gate iterations:
```json
{
  "agent_overrides": {"review_a": "claude-opus", "review_b": "cursor-codex-xhigh"},
  "step_overrides": {"select": {"pr_numbers": [123]}, "prioritize": {"max_batch": 5}},
  "human_feedback": [
    {"gate_step_id": "prompt_gate", "retry_target": "experts",
     "feedback": "Focus more on security", "iteration": 1}
  ]
}
```

**Environment**: Requires `gh` CLI in PATH (for GitHub API calls), `claude` CLI (for Claude agent), optionally `agent` CLI (for Cursor), `OPENAI_API_KEY` env var (for OpenAI agent).
