"""Agent registry — instantiates agent backends by name from config or DB."""

import logging
from typing import Optional

from backend.agents.base import AgentBackend
from backend.agents.claude_cli import ClaudeCLIAgent
from backend.agents.cursor_cli import CursorCLIAgent
from backend.agents.openai_api import OpenAIAgent

logger = logging.getLogger(__name__)

_AGENT_TYPES = {
    "claude_cli": ClaudeCLIAgent,
    "cursor_cli": CursorCLIAgent,
    "openai_api": OpenAIAgent,
}

_instance_cache: dict[str, AgentBackend] = {}


def get_agent(name: str, agent_config: Optional[dict] = None) -> AgentBackend:
    """Get or create an agent backend by name.

    If agent_config is provided, it must include 'type' (one of the registered types).
    Otherwise, falls back to the app config.json agents section.
    """
    if name in _instance_cache:
        return _instance_cache[name]

    if agent_config is None:
        from backend.config import get_config
        config = get_config()
        agents_cfg = config.get("agents", {})
        agent_config = agents_cfg.get(name)

    if agent_config is None:
        try:
            import json as _json
            from backend.database import get_workflow_db
            db = get_workflow_db()
            for row in db.list_agents():
                if row["name"] == name:
                    if not row.get("is_active", True):
                        logger.debug(f"Agent '{name}' found in DB but is_active=False, skipping")
                        continue
                    extra = row.get("config_json") or "{}"
                    if isinstance(extra, str):
                        extra = _json.loads(extra)
                    agent_config = {
                        "type": row["type"],
                        "model": row.get("model", ""),
                        **extra,
                    }
                    break
        except Exception as e:
            logger.warning(f"DB fallback lookup for agent '{name}' failed: {e}")

    if agent_config is None:
        raise ValueError(f"Unknown agent '{name}' and no config provided")

    agent_type = agent_config.get("type", "claude_cli")
    cls = _AGENT_TYPES.get(agent_type)
    if cls is None:
        raise ValueError(f"Unknown agent type '{agent_type}'. Available: {list(_AGENT_TYPES.keys())}")

    instance = cls(name=name, config=agent_config)
    _instance_cache[name] = instance
    logger.info(f"Registered agent '{name}' (type={agent_type})")
    return instance


def list_agents() -> list[dict]:
    """List all configured agents from config.json."""
    from backend.config import get_config
    config = get_config()
    agents_cfg = config.get("agents", {})
    result = []
    for name, cfg in agents_cfg.items():
        result.append({
            "name": name,
            "type": cfg.get("type", "claude_cli"),
            "model": cfg.get("model", "unknown"),
        })
    if not result:
        result.append({"name": "claude", "type": "claude_cli", "model": "opus"})
    return result


def register_agent_type(type_name: str, cls: type):
    """Register a custom agent backend type."""
    _AGENT_TYPES[type_name] = cls


def clear_cache():
    """Clear the agent instance cache (useful for testing)."""
    _instance_cache.clear()
