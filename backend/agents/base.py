"""AgentBackend ABC — the pluggable interface all AI backends implement."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class AgentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class AgentHandle:
    """Opaque handle returned by start_review, used to poll/cancel."""
    agent_name: str
    handle_id: str
    metadata: dict = field(default_factory=dict)


@dataclass
class ReviewArtifact:
    """Output of a completed agent review."""
    content_md: Optional[str] = None
    content_json: Optional[dict] = None
    file_path: Optional[str] = None
    score: Optional[float] = None
    error: Optional[str] = None
    usage: Optional[dict] = None  # {input_tokens, output_tokens, cost_usd, ...}


_USAGE_KEY_MAP = {
    "inputTokens": "input_tokens",
    "outputTokens": "output_tokens",
    "cacheReadTokens": "cache_read_input_tokens",
    "cacheWriteTokens": "cache_creation_input_tokens",
}


def normalize_usage(raw: dict) -> dict:
    """Normalize camelCase usage keys (Cursor) to snake_case (Claude convention)."""
    out = {}
    for k, v in raw.items():
        out[_USAGE_KEY_MAP.get(k, k)] = v
    return out


class AgentBackend(ABC):
    """Base class for all AI agent backends.

    Subclasses implement the three lifecycle methods:
      start_review  -> AgentHandle
      check_status  -> AgentStatus
      get_output    -> ReviewArtifact
    Plus an optional cancel method.
    """

    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config

    @abstractmethod
    def start_review(self, prompt: str, context: dict) -> AgentHandle:
        """Begin an async review. Returns a handle for polling."""

    @abstractmethod
    def check_status(self, handle: AgentHandle) -> AgentStatus:
        """Poll whether the review is still running."""

    @abstractmethod
    def get_output(self, handle: AgentHandle) -> ReviewArtifact:
        """Retrieve the finished review artifact. Only valid after COMPLETED status."""

    def get_live_output(self, handle: AgentHandle) -> str:
        """Return partial stdout captured so far from a running agent. Empty if not supported."""
        return ""

    def cancel(self, handle: AgentHandle) -> bool:
        """Attempt to cancel a running review. Returns True if cancelled."""
        return False

    def cleanup(self, handle: AgentHandle) -> None:
        """Release resources (file descriptors, process entries) after a review completes or is cancelled."""
