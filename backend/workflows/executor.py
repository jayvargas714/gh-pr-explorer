"""StepExecutor base class — the interface all workflow steps implement."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class StepResult:
    """Output of a step execution."""
    success: bool = True
    outputs: dict = field(default_factory=dict)
    artifacts: list = field(default_factory=list)
    error: Optional[str] = None
    awaiting_gate: bool = False
    gate_payload: Optional[dict] = None


class StepExecutor(ABC):
    """Base class for all workflow step executors.

    Each step type implements execute() which receives the step config
    and accumulated inputs from upstream steps, and returns a StepResult.
    """

    def __init__(self, step_config: dict, instance_config: dict):
        self.step_config = step_config
        self.instance_config = instance_config

    @abstractmethod
    def execute(self, inputs: dict) -> StepResult:
        """Run the step. May block for long-running operations (agent calls).

        Args:
            inputs: merged outputs from all upstream steps

        Returns:
            StepResult with outputs for downstream steps and any artifacts produced
        """

    def validate_config(self) -> list[str]:
        """Validate this step's configuration. Returns list of error messages (empty = valid)."""
        return []
