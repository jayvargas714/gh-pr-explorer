"""Seed built-in workflow templates and agents on startup."""

import json
import logging

from backend.database import get_workflow_db

logger = logging.getLogger(__name__)

QUICK_REVIEW_TEMPLATE = {
    "steps": [
        {"id": "select", "type": "pr_select", "config": {"mode": "quick"}, "position": {"x": 100, "y": 200}},
        {"id": "prompt", "type": "prompt_generate", "config": {}, "position": {"x": 300, "y": 200}},
        {"id": "review", "type": "agent_review", "config": {"agent": "claude"}, "position": {"x": 500, "y": 200}},
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
        {"id": "review_a", "type": "agent_review", "config": {"agent": "claude"}, "position": {"x": 500, "y": 100}},
        {"id": "review_b", "type": "agent_review", "config": {"agent": "openai"}, "position": {"x": 500, "y": 300}},
        {"id": "synth", "type": "synthesis", "config": {}, "position": {"x": 650, "y": 200}},
        {"id": "fresh", "type": "freshness_check", "config": {}, "position": {"x": 800, "y": 200}},
        {"id": "gate", "type": "human_gate", "config": {}, "position": {"x": 950, "y": 200}},
        {"id": "pub", "type": "publish", "config": {}, "position": {"x": 1100, "y": 200}},
    ],
    "edges": [
        {"from": "select", "to": "prioritize", "condition": None},
        {"from": "prioritize", "to": "prompt", "condition": None},
        {"from": "prompt", "to": "review_a", "condition": None},
        {"from": "prompt", "to": "review_b", "condition": None},
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
        {"id": "review_a", "type": "agent_review", "config": {"agent": "claude"}, "position": {"x": 500, "y": 100}},
        {"id": "review_b", "type": "agent_review", "config": {"agent": "openai"}, "position": {"x": 500, "y": 300}},
        {"id": "synth", "type": "synthesis", "config": {}, "position": {"x": 650, "y": 200}},
        {"id": "holistic", "type": "holistic_review", "config": {}, "position": {"x": 800, "y": 200}},
        {"id": "gate", "type": "human_gate", "config": {}, "position": {"x": 950, "y": 200}},
    ],
    "edges": [
        {"from": "select", "to": "experts", "condition": None},
        {"from": "experts", "to": "prompt", "condition": None},
        {"from": "prompt", "to": "review_a", "condition": None},
        {"from": "prompt", "to": "review_b", "condition": None},
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
        {"id": "review_a", "type": "agent_review", "config": {"agent": "claude"}, "position": {"x": 500, "y": 100}},
        {"id": "review_b", "type": "agent_review", "config": {"agent": "openai"}, "position": {"x": 500, "y": 300}},
        {"id": "synth", "type": "synthesis", "config": {}, "position": {"x": 650, "y": 200}},
        {"id": "holistic", "type": "holistic_review", "config": {}, "position": {"x": 800, "y": 200}},
        {"id": "gate", "type": "human_gate", "config": {}, "position": {"x": 950, "y": 200}},
        {"id": "pub", "type": "publish", "config": {}, "position": {"x": 1100, "y": 200}},
    ],
    "edges": [
        {"from": "select", "to": "experts", "condition": None},
        {"from": "experts", "to": "prompt", "condition": None},
        {"from": "prompt", "to": "review_a", "condition": None},
        {"from": "prompt", "to": "review_b", "condition": None},
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

BUILTIN_TEMPLATES = [
    ("Quick Review", "Single-agent, single-pass review (Jay's original flow)", QUICK_REVIEW_TEMPLATE),
    ("Team Review", "Dual-agent adversarial review with synthesis, human gate, and publication", TEAM_REVIEW_TEMPLATE),
    ("Self-Review", "Multi-expert deep-dive for self-authored PRs (local only)", SELF_REVIEW_TEMPLATE),
    ("Deep Review", "Multi-expert deep-dive for external PRs with publication", DEEP_REVIEW_TEMPLATE),
]

BUILTIN_AGENTS = [
    ("claude", "claude_cli", "opus", {}),
    ("openai", "openai_api", "gpt-4o", {"api_key_env": "OPENAI_API_KEY"}),
    ("cursor-opus", "cursor_cli", "opus-4.6-thinking", {"sandbox": "disabled"}),
    ("cursor-codex", "cursor_cli", "gpt-5.3-codex-high", {"sandbox": "disabled"}),
    ("cursor-codex-xh", "cursor_cli", "gpt-5.4-xhigh", {"sandbox": "disabled"}),
]


def seed_builtin_data():
    """Seed built-in templates and agents. Safe to call on every startup."""
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

    logger.info("Workflow engine seed data complete")
