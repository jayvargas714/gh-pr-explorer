"""Seed built-in workflow templates, agents, expert domains, and code owners."""

import json
import logging

from backend.database import get_workflow_db

logger = logging.getLogger(__name__)

QUICK_REVIEW_TEMPLATE = {
    "steps": [
        {"id": "select", "type": "pr_select", "config": {"mode": "quick"}, "position": {"x": 100, "y": 200}},
        {"id": "prompt", "type": "prompt_generate", "config": {}, "position": {"x": 300, "y": 200}},
        {"id": "review", "type": "agent_review", "config": {"agent": "cursor-opus"}, "position": {"x": 500, "y": 200}},
    ],
    "edges": [
        {"from": "select", "to": "prompt", "condition": None},
        {"from": "prompt", "to": "review", "condition": None},
    ],
    "fan_out_groups": [],
}

TEAM_REVIEW_TEMPLATE = {
    "steps": [
        {"id": "select", "type": "pr_select", "config": {"mode": "team-review"}, "position": {"x": 50, "y": 200}},
        {"id": "prioritize", "type": "prioritize", "config": {}, "position": {"x": 200, "y": 200}},
        {"id": "prompt", "type": "prompt_generate", "config": {}, "position": {"x": 350, "y": 200}},
        {"id": "prompt_gate", "type": "human_gate", "config": {"gate_type": "prompt_review", "retry_target": "prompt"}, "position": {"x": 400, "y": 200}},
        {"id": "review_a", "type": "agent_review", "config": {"agent": "cursor-opus", "phase": "a"}, "position": {"x": 600, "y": 100}},
        {"id": "review_b", "type": "agent_review", "config": {"agent": "cursor-codex-xh", "phase": "b"}, "position": {"x": 600, "y": 300}},
        {"id": "synth", "type": "synthesis", "config": {"ai_verify": True}, "position": {"x": 750, "y": 200}},
        {"id": "fresh", "type": "freshness_check", "config": {}, "position": {"x": 900, "y": 200}},
        {"id": "gate", "type": "human_gate", "config": {"retry_target": "synth"}, "position": {"x": 1050, "y": 200}},
        {"id": "pub", "type": "publish", "config": {}, "position": {"x": 1200, "y": 200}},
    ],
    "edges": [
        {"from": "select", "to": "prioritize", "condition": None},
        {"from": "prioritize", "to": "prompt", "condition": None},
        {"from": "prompt", "to": "prompt_gate", "condition": None},
        {"from": "prompt_gate", "to": "review_a", "condition": None},
        {"from": "prompt_gate", "to": "review_b", "condition": None},
        {"from": "review_a", "to": "synth", "condition": None},
        {"from": "review_b", "to": "synth", "condition": None},
        {"from": "synth", "to": "fresh", "condition": None},
        {"from": "fresh", "to": "gate", "condition": None},
        {"from": "gate", "to": "pub", "condition": None},
    ],
    "fan_out_groups": [],
}

SELF_REVIEW_TEMPLATE = {
    "steps": [
        {"id": "select", "type": "pr_select", "config": {"mode": "self-review"}, "position": {"x": 50, "y": 200}},
        {"id": "experts", "type": "expert_select", "config": {}, "position": {"x": 200, "y": 200}},
        {"id": "prompt", "type": "prompt_generate", "config": {"per_expert": True}, "position": {"x": 350, "y": 200}},
        {"id": "prompt_gate", "type": "human_gate", "config": {"gate_type": "prompt_review", "retry_target": "experts"}, "position": {"x": 400, "y": 200}},
        {"id": "review_a", "type": "agent_review", "config": {"agent": "cursor-opus", "phase": "a"}, "position": {"x": 600, "y": 100}},
        {"id": "review_b", "type": "agent_review", "config": {"agent": "cursor-codex-xh", "phase": "b"}, "position": {"x": 600, "y": 300}},
        {"id": "synth", "type": "synthesis", "config": {"ai_verify": True}, "position": {"x": 750, "y": 200}},
        {"id": "holistic", "type": "holistic_review", "config": {"agent": "cursor-opus"}, "position": {"x": 900, "y": 200}},
        {"id": "gate", "type": "human_gate", "config": {"retry_target": "synth"}, "position": {"x": 1050, "y": 200}},
    ],
    "edges": [
        {"from": "select", "to": "experts", "condition": None},
        {"from": "experts", "to": "prompt", "condition": None},
        {"from": "prompt", "to": "prompt_gate", "condition": None},
        {"from": "prompt_gate", "to": "review_a", "condition": None},
        {"from": "prompt_gate", "to": "review_b", "condition": None},
        {"from": "review_a", "to": "synth", "condition": None},
        {"from": "review_b", "to": "synth", "condition": None},
        {"from": "synth", "to": "holistic", "condition": None},
        {"from": "holistic", "to": "gate", "condition": None},
    ],
    "fan_out_groups": [
        {"source": "experts", "targets": ["prompt"], "key": "domain"},
    ],
}

DEEP_REVIEW_TEMPLATE = {
    "steps": [
        {"id": "select", "type": "pr_select", "config": {"mode": "deep-review"}, "position": {"x": 50, "y": 200}},
        {"id": "experts", "type": "expert_select", "config": {}, "position": {"x": 200, "y": 200}},
        {"id": "prompt", "type": "prompt_generate", "config": {"per_expert": True}, "position": {"x": 350, "y": 200}},
        {"id": "prompt_gate", "type": "human_gate", "config": {"gate_type": "prompt_review", "retry_target": "experts"}, "position": {"x": 400, "y": 200}},
        {"id": "review_a", "type": "agent_review", "config": {"agent": "cursor-opus", "phase": "a"}, "position": {"x": 600, "y": 100}},
        {"id": "review_b", "type": "agent_review", "config": {"agent": "cursor-codex-xh", "phase": "b"}, "position": {"x": 600, "y": 300}},
        {"id": "synth", "type": "synthesis", "config": {"ai_verify": True}, "position": {"x": 750, "y": 200}},
        {"id": "holistic", "type": "holistic_review", "config": {"agent": "cursor-opus"}, "position": {"x": 900, "y": 200}},
        {"id": "gate", "type": "human_gate", "config": {"retry_target": "synth"}, "position": {"x": 1050, "y": 200}},
        {"id": "pub", "type": "publish", "config": {}, "position": {"x": 1200, "y": 200}},
    ],
    "edges": [
        {"from": "select", "to": "experts", "condition": None},
        {"from": "experts", "to": "prompt", "condition": None},
        {"from": "prompt", "to": "prompt_gate", "condition": None},
        {"from": "prompt_gate", "to": "review_a", "condition": None},
        {"from": "prompt_gate", "to": "review_b", "condition": None},
        {"from": "review_a", "to": "synth", "condition": None},
        {"from": "review_b", "to": "synth", "condition": None},
        {"from": "synth", "to": "holistic", "condition": None},
        {"from": "holistic", "to": "gate", "condition": None},
        {"from": "gate", "to": "pub", "condition": None},
    ],
    "fan_out_groups": [
        {"source": "experts", "targets": ["prompt"], "key": "domain"},
    ],
}

FOLLOWUP_TEMPLATE = {
    "steps": [
        {"id": "check", "type": "followup_check", "config": {}, "position": {"x": 100, "y": 200}},
        {"id": "gate", "type": "human_gate", "config": {"retry_target": "check"}, "position": {"x": 400, "y": 200}},
        {"id": "action", "type": "followup_action", "config": {}, "position": {"x": 700, "y": 200}},
    ],
    "edges": [
        {"from": "check", "to": "gate", "condition": None},
        {"from": "gate", "to": "action", "condition": None},
    ],
    "fan_out_groups": [],
}

BUILTIN_TEMPLATES = [
    ("Quick Review", "Single-agent, single-pass review (Jay's original flow)", QUICK_REVIEW_TEMPLATE),
    ("Team Review", "Dual-agent adversarial review with synthesis, human gate, and publication", TEAM_REVIEW_TEMPLATE),
    ("Self-Review", "Multi-expert deep-dive for self-authored PRs (local only)", SELF_REVIEW_TEMPLATE),
    ("Deep Review", "Multi-expert deep-dive for external PRs with publication", DEEP_REVIEW_TEMPLATE),
    ("Follow-Up Review", "Re-check published reviews after author responds", FOLLOWUP_TEMPLATE),
]

BUILTIN_AGENTS = [
    ("cursor-opus", "cursor_cli", "opus-4.6-thinking", {"sandbox": "disabled"}),
    ("cursor-codex", "cursor_cli", "gpt-5.3-codex-high", {"sandbox": "disabled"}),
    ("cursor-codex-xh", "cursor_cli", "gpt-5.4-xhigh", {"sandbox": "disabled"}),
    ("openai", "openai_api", "gpt-4o", {"api_key_env": "OPENAI_API_KEY"}),
    ("claude", "claude_cli", "opus", {}),
]

CODE_OWNERS = [
    ("scalazack", "Zack", 20),
    ("scala-eric", "Eric", 15),
    ("jayvargas714", "Jay", 10),
    ("kwoo-scalacomputing", "Kelvin", 5),
    ("amartinat-scala", "Amery", 0),
]

# 10 expert domains from the legacy adversarial review system
BUILTIN_EXPERT_DOMAINS = [
    {
        "domain_id": "rust-api",
        "display_name": "Rust API",
        "repo": "scala-computing/scala",
        "persona": (
            "Principal Rust engineer specializing in async web services. Deep expertise in "
            "Axum/Tower middleware stacks, typed extractors, error handling (IntoResponse, "
            "ServiceError enums), HTTP semantics (idempotency, status codes, content negotiation), "
            "request validation. Focus on API contract stability, backward compatibility, "
            "defense-in-depth. Knows serde sharp edges (rename_all, default, deny_unknown_fields) "
            "and error message safety (no internal details in 4xx/5xx responses)."
        ),
        "scope": "Axum routes, HTTP handlers, middleware, request/response types, error mapping",
        "triggers": {
            "file_patterns": [r"routes/.*\.rs", r"server/.*\.rs"],
            "keywords": ["axum::", "StatusCode", "handler", "into_response", "IntoResponse"],
        },
        "checklist": [
            "Does each new route have proper error mapping to HTTP status codes?",
            "Are request types validated before business logic runs?",
            "Do error responses avoid leaking internal details?",
            "Is backward compatibility maintained for existing API contracts?",
            "Are serde attributes correct (rename_all, deny_unknown_fields where appropriate)?",
            "Is idempotency handled for non-GET endpoints?",
            "Are middleware applied consistently across related routes?",
        ],
        "anti_patterns": [
            "Returning 500 with internal error details in response body",
            "Missing Content-Type validation on request handlers",
            "Unwrap/expect in handler code paths (panics = DoS)",
            "Inconsistent error enum variants across related routes",
        ],
    },
    {
        "domain_id": "database",
        "display_name": "Database",
        "repo": "scala-computing/scala",
        "persona": (
            "Principal database engineer specializing in PostgreSQL and SQLx. Deep expertise in "
            "transaction isolation, advisory locks, migration safety (backward-compatible schema "
            "changes, zero-downtime deploys), query performance (index usage, sequential scans, "
            "N+1), connection pool management. Reviews SQL for injection, type coercion, NULL "
            "handling. Understands transactional atomicity vs performance."
        ),
        "scope": "SQLx queries, PostgreSQL, transactions, migrations, models, schema",
        "triggers": {
            "file_patterns": [r"models/.*\.rs", r"migrations/"],
            "keywords": ["sqlx::", "BEGIN", "COMMIT", "transaction", ".execute("],
        },
        "checklist": [
            "Are migrations backward-compatible with the previous schema version?",
            "Do transactions have appropriate isolation levels?",
            "Are N+1 query patterns avoided?",
            "Is NULL handling explicit (not relying on implicit defaults)?",
            "Are indexes present for new query patterns?",
            "Is connection pool exhaustion considered under load?",
            "Are rollback errors handled (not silently discarded)?",
        ],
        "anti_patterns": [
            "let _ = tx.rollback() silently discards rollback errors",
            "Status update outside transaction creates atomicity gap",
            "Sequential scan on large table without LIMIT",
            "Missing index on foreign key column used in JOIN",
        ],
    },
    {
        "domain_id": "s3-cloud",
        "display_name": "S3/Cloud",
        "repo": "scala-computing/scala",
        "persona": (
            "Principal cloud infrastructure engineer specializing in AWS S3. Deep expertise in "
            "multipart upload lifecycle (create -> upload parts -> complete/abort), presigned URL "
            "security (expiration, scoping), CAS patterns, S3 consistency model, cost optimization "
            "(storage classes, lifecycle rules). Reviews for resource leaks (orphaned multiparts, "
            "dangling objects), eventual consistency pitfalls, IAM scope."
        ),
        "scope": "AWS SDK, S3 multipart upload lifecycle, presigned URLs, CAS, object storage",
        "triggers": {
            "file_patterns": [],
            "keywords": ["s3_client", "multipart", "presign", "upload_id",
                         "complete_multipart", "abort_multipart", "copy_object"],
        },
        "checklist": [
            "Are multipart uploads always completed or aborted (no orphans)?",
            "Do presigned URLs have appropriate expiration and scoping?",
            "Is eventual consistency handled for read-after-write scenarios?",
            "Are IAM permissions scoped to minimum required?",
            "Is error handling present for partial upload failures?",
            "Are storage class transitions configured correctly?",
        ],
        "anti_patterns": [
            "Missing abort_multipart on error path (resource leak)",
            "Presigned URL with no expiration or overly broad scope",
            "Read-after-write assuming strong consistency",
        ],
    },
    {
        "domain_id": "concurrency",
        "display_name": "Concurrency",
        "repo": "scala-computing/scala",
        "persona": (
            "Principal systems engineer specializing in concurrent and async Rust. Deep expertise "
            "in state machines, OCC, tokio runtime, cancellation safety, Send/Sync, lock ordering, "
            "race detection. Reviews for deadlocks, TOCTOU, starvation, priority inversion. Treats "
            "'it works on my machine' as irrelevant for concurrency bugs."
        ),
        "scope": "State machines, OCC, atomics, async patterns, cancellation, race conditions",
        "triggers": {
            "file_patterns": [],
            "keywords": ["claim_", "status.*transition", "Mutex", "RwLock", "atomic",
                         "race", "CancellationToken", "OCC", "competing"],
        },
        "checklist": [
            "Does the claim/transition have a recovery path on every post-claim error?",
            "Are locks acquired in a consistent order to prevent deadlocks?",
            "Is cancellation safety maintained (no resource leaks on cancel)?",
            "Are TOCTOU windows identified and mitigated?",
            "Is the state machine transition valid from every possible current state?",
            "Are atomic operations using the correct memory ordering?",
        ],
        "anti_patterns": [
            "OCC claim before validation (strands state on validation failure)",
            "TOCTOU between status read and atomic update",
            "Lock held across await point (deadlock risk in async)",
            "Missing CancellationToken propagation in spawned tasks",
        ],
    },
    {
        "domain_id": "security",
        "display_name": "Security",
        "repo": "scala-computing/scala",
        "persona": (
            "Principal application security engineer. Deep expertise in input validation (OWASP "
            "Top 10), path traversal prevention, injection (SQL, command, SSRF), auth/authz "
            "(RBAC, ABAC), secrets management, secure defaults. Red-team mindset. Checks error "
            "messages for leakage, deny-by-default, logic bypasses. Aware of Rust-specific "
            "concerns (panic as DoS, unsafe, integer overflow in release)."
        ),
        "scope": "Input validation, path traversal, auth/authz, injection, RBAC, secrets",
        "triggers": {
            "file_patterns": [],
            "keywords": ["validate_", "sanitize", "traversal", "../", "role",
                         "permission", "auth", "RBAC", "secret", "credential"],
        },
        "checklist": [
            "Is all user input validated before use?",
            "Are path traversal attacks prevented (no ../ in file paths)?",
            "Is authorization checked at every access point (deny-by-default)?",
            "Are secrets stored securely (not in code, not in logs)?",
            "Do error messages avoid leaking internal implementation details?",
            "Are SQL/command injection vectors eliminated?",
            "Is integer overflow handled in release builds?",
        ],
        "anti_patterns": [
            "&str[..n] indexing panics on multi-byte UTF-8",
            'contains("..") catches non-traversal patterns like file..ext',
            "Permission check only at API boundary, not at service layer",
            "Logging secrets or tokens in error messages",
        ],
    },
    {
        "domain_id": "testing",
        "display_name": "Testing",
        "repo": "scala-computing/scala",
        "persona": (
            "Principal QA/test architect. Deep expertise in test pyramid, integration harnesses, "
            "property-based testing, mutation testing, coverage analysis. Reviews for: test "
            "isolation, assertion quality (behavior vs implementation), edge cases (boundaries, "
            "empty inputs, concurrency), harness rules. Critical of tests that assert 200 OK "
            "without checking response body."
        ),
        "scope": "Test coverage gaps, harness compliance, edge case adequacy, test architecture",
        "triggers": {
            "file_patterns": [r"tests/", r"#\[test\]", r"#\[tokio::test\]"],
            "keywords": ["assert", "mock", "fixture"],
        },
        "checklist": [
            "Do new features have corresponding test coverage?",
            "Are assertions checking behavior, not implementation details?",
            "Are edge cases covered (empty input, boundary values, error paths)?",
            "Is test isolation maintained (no shared mutable state between tests)?",
            "Are integration tests using proper harness setup/teardown?",
            "Do tests avoid sleep/timeouts as synchronization?",
        ],
        "anti_patterns": [
            "Test asserts 200 OK without checking response body",
            "Sleep-based synchronization in async tests",
            "Shared mutable state between test cases",
            "Mock that mirrors implementation rather than contract",
        ],
    },
    {
        "domain_id": "infra-ci",
        "display_name": "Infra/CI",
        "repo": "scala-computing/scala",
        "persona": (
            "Principal DevSecOps engineer. Deep expertise in Docker multi-stage builds, CI/CD "
            "(GitHub Actions), IaC (Terraform), IAM least-privilege, secrets rotation, supply "
            "chain security. Reviews for reproducible builds, layer cache, privilege escalation "
            "in containers, overly broad IAM, CI injection risks."
        ),
        "scope": "Docker, CI pipelines, IaC, Terraform, deployment, Makefiles",
        "triggers": {
            "file_patterns": ["Dockerfile", r"\.github/", "Makefile", "justfile",
                              r"terraform/", r"\.tf$", "docker-compose"],
            "keywords": [],
        },
        "checklist": [
            "Are Docker images using multi-stage builds with minimal final image?",
            "Are CI secrets not exposed in logs or artifacts?",
            "Is IAM following least-privilege principle?",
            "Are container images pinned to specific digests (not :latest)?",
            "Is Terraform state properly managed and locked?",
            "Are CI pipeline inputs sanitized against injection?",
        ],
        "anti_patterns": [
            "Running container as root without justification",
            "CI pipeline using pull_request_target with checkout of PR code",
            "Overly broad IAM policy (Action: * or Resource: *)",
        ],
    },
    {
        "domain_id": "go-backend",
        "display_name": "Go Backend",
        "repo": "scala-computing/scala",
        "persona": (
            "Principal Go engineer specializing in backend services. Deep expertise in goroutine "
            "lifecycle, context propagation, connection pool tuning, interface design, error "
            "wrapping. Reviews for goroutine leaks, missing defer cleanup, nil dereferences, "
            "race conditions (go vet -race), improper error sentinel comparisons."
        ),
        "scope": "Go HTTP handlers, goroutines, channels, connection pools, error handling",
        "triggers": {
            "file_patterns": [r".*\.go$", "go.mod"],
            "keywords": ["goroutine", "chan ", "sync.", "http.Handler"],
        },
        "checklist": [
            "Are goroutines properly lifecycle-managed (no leaks)?",
            "Is context propagation correct through the call chain?",
            "Are defer statements used for cleanup (connections, files)?",
            "Are error sentinels compared with errors.Is, not ==?",
            "Is the connection pool sized appropriately?",
            "Are nil pointer dereferences guarded against?",
        ],
        "anti_patterns": [
            "Goroutine spawned without cancellation or WaitGroup",
            "Missing defer conn.Close() after pool checkout",
            "Error comparison with == instead of errors.Is",
            "Channel send without select/timeout (potential deadlock)",
        ],
    },
    {
        "domain_id": "cpp-simulator",
        "display_name": "C++ Simulator",
        "repo": "scala-computing/scala",
        "persona": (
            "Principal C++ engineer specializing in network simulation. Deep expertise in NS3, "
            "memory management (RAII, smart pointers), congestion control algorithms, simulation "
            "correctness. Reviews for memory leaks, use-after-free, undefined behavior, numerical "
            "stability, simulation determinism."
        ),
        "scope": "NS3, C++ memory management, CC algorithms, simulation correctness",
        "triggers": {
            "file_patterns": [r".*\.cc$", r".*\.cpp$", r".*\.h$"],
            "keywords": ["ns3::", "Simulator::", "congestion", "cwnd"],
        },
        "checklist": [
            "Is memory managed via RAII/smart pointers (no raw new/delete)?",
            "Are use-after-free and double-free risks eliminated?",
            "Is numerical stability maintained in CC calculations?",
            "Is simulation determinism preserved (no uninitialized state)?",
            "Are NS3 callbacks properly prevented from dangling?",
            "Is undefined behavior avoided (signed overflow, null deref)?",
        ],
        "anti_patterns": [
            "Raw pointer without clear ownership semantics",
            "Uninitialized variable used in simulation state",
            "Floating-point comparison with == in CC algorithm",
        ],
    },
    {
        "domain_id": "python-tooling",
        "display_name": "Python Tooling",
        "repo": "scala-computing/scala",
        "persona": (
            "Principal Python toolchain engineer. Deep expertise in dependency management (pip, "
            "poetry), virtual environments, supply chain security (typosquatting, pinning), "
            "script correctness. Reviews for unpinned dependencies, subprocess injection, path "
            "handling on Windows vs Unix, missing error handling in scripts."
        ),
        "scope": "Python dependencies, supply chain, scripting, packaging",
        "triggers": {
            "file_patterns": [r".*\.py$", "requirements.txt", "pyproject.toml", "setup.py"],
            "keywords": ["pip"],
        },
        "checklist": [
            "Are all dependencies pinned to specific versions?",
            "Is subprocess invocation safe from injection?",
            "Are file paths handled cross-platform (pathlib, not string concat)?",
            "Is error handling present for external tool invocations?",
            "Are virtual environments used to isolate dependencies?",
        ],
        "anti_patterns": [
            "Unpinned dependency in requirements.txt",
            "subprocess.run with shell=True and user input",
            "os.path.join with unsanitized user input",
        ],
    },
]


def seed_builtin_data():
    """Seed built-in templates, agents, expert domains, and code owners.
    Safe to call on every startup."""
    db = get_workflow_db()

    for name, description, template in BUILTIN_TEMPLATES:
        existing = db.get_template_by_name(name)
        if existing is None:
            db.create_template(name, description, template, is_builtin=True)
            logger.info(f"Seeded built-in template: {name}")
        else:
            logger.debug(f"Built-in template '{name}' already exists")

    for name, agent_type, model, config in BUILTIN_AGENTS:
        db.upsert_agent(name, agent_type, model, config)
        logger.debug(f"Upserted agent: {name}")

    for domain_def in BUILTIN_EXPERT_DOMAINS:
        db.upsert_expert_domain(
            domain_id=domain_def["domain_id"],
            display_name=domain_def["display_name"],
            persona=domain_def["persona"],
            scope=domain_def["scope"],
            triggers=domain_def["triggers"],
            checklist=domain_def["checklist"],
            anti_patterns=domain_def.get("anti_patterns", []),
            is_builtin=True,
            repo=domain_def.get("repo"),
        )
        logger.debug(f"Upserted expert domain: {domain_def['domain_id']}")

    _seed_code_owners(db)

    logger.info("Workflow engine seed data complete")


def _seed_code_owners(db):
    """Seed code owner registry from legacy adversarial review spec."""
    for handle, name, boost in CODE_OWNERS:
        db.upsert_code_owner(handle, name, boost)
