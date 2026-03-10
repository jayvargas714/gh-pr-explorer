"""Step type registry — maps step type names to executor classes."""

from enum import Enum


class StepType(str, Enum):
    PR_SELECT = "pr_select"
    PRIORITIZE = "prioritize"
    EXPERT_SELECT = "expert_select"
    PROMPT_GENERATE = "prompt_generate"
    AGENT_REVIEW = "agent_review"
    SYNTHESIS = "synthesis"
    HOLISTIC_REVIEW = "holistic_review"
    FRESHNESS_CHECK = "freshness_check"
    HUMAN_GATE = "human_gate"
    PUBLISH = "publish"
    RELATED_ISSUE_SCAN = "related_issue_scan"
    FP_SEVERITY_CHECK = "fp_severity_check"
    FOLLOWUP_CHECK = "followup_check"
    FOLLOWUP_ACTION = "followup_action"


STEP_REGISTRY: dict[str, type] = {}


def register_step(step_type: str):
    """Decorator to register a StepExecutor subclass for a step type."""
    def decorator(cls):
        STEP_REGISTRY[step_type] = cls
        return cls
    return decorator


def get_executor_class(step_type: str) -> type:
    """Look up the executor class for a step type."""
    cls = STEP_REGISTRY.get(step_type)
    if cls is None:
        raise ValueError(f"No executor registered for step type '{step_type}'. "
                         f"Available: {list(STEP_REGISTRY.keys())}")
    return cls
