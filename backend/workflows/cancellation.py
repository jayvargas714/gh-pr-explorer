"""Instance cancellation registry.

Provides a cooperative cancellation mechanism for running workflow instances.
cancel_instance() signals cancellation and terminates any registered agent handles.
Polling loops check is_cancelled() to exit early.
"""

import logging
import threading

logger = logging.getLogger(__name__)

_cancelled: set[int] = set()
_lock = threading.Lock()

_active_agents: dict[int, list[tuple]] = {}
_agent_lock = threading.Lock()

AGENT_POLL_TIMEOUT = 1800  # 30 minutes max per agent poll loop


def cancel(instance_id: int) -> None:
    """Signal cancellation for an instance and terminate registered agents."""
    with _lock:
        _cancelled.add(instance_id)

    with _agent_lock:
        entries = _active_agents.pop(instance_id, [])
    for agent_ref, handle_ref in entries:
        try:
            agent_ref.cancel(handle_ref)
        except Exception as e:
            logger.warning(f"Error cancelling agent for instance {instance_id}: {e}")


def is_cancelled(instance_id: int) -> bool:
    with _lock:
        return instance_id in _cancelled


def clear(instance_id: int) -> None:
    with _lock:
        _cancelled.discard(instance_id)
    with _agent_lock:
        _active_agents.pop(instance_id, None)


def register_agent(instance_id: int, agent_ref, handle_ref) -> None:
    with _agent_lock:
        _active_agents.setdefault(instance_id, []).append((agent_ref, handle_ref))


def unregister_agent(instance_id: int, handle_ref) -> None:
    with _agent_lock:
        entries = _active_agents.get(instance_id, [])
        _active_agents[instance_id] = [
            (a, h) for a, h in entries if h is not handle_ref
        ]
