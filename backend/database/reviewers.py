"""ReviewersDB - Configurable reviewer registry.

Seeded with the three builtin reviewers previously hardcoded in
review_service.py. Builtins can be relabeled and given new prompt context,
but their agent name is locked and they cannot be deleted — other tooling
(and the auto-verdict arming columns) expects those agents to exist.
"""

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

KEY_PATTERN = re.compile(r"^[a-z0-9_-]{1,32}$")

# The exact prompt-context strings that used to live in start_review_process.
BUILTIN_REVIEWERS = [
    {
        "key": "default",
        "label": "Default Reviewer",
        "agent_name": "elite-code-reviewer",
        "prompt_context": None,
    },
    {
        "key": "pb",
        "label": "PB Reviewer",
        "agent_name": "product-brief-reviewer",
        "prompt_context": (
            "This PR adds or modifies a product brief (a PB-NNN-*.md file under briefs/). "
            "Identify the brief file(s) touched in the PR diff and review them against the PB-000 template "
            "and the rules embedded in the product-brief-reviewer agent. Quote evidence verbatim and keep "
            "all fixes in user-observable, product-level language. "
        ),
    },
    {
        "key": "ed",
        "label": "ED Reviewer",
        "agent_name": "ed-reviewer",
        "prompt_context": (
            "This PR adds or modifies an engineering design (an ED-NNN-*.md file under docs/designs/). "
            "Identify the ED file(s) touched in the PR diff and review them against the ED-000 template "
            "and the rules embedded in the ed-reviewer agent. Apply both lenses: SDLC conformance "
            "(SPEC-AUTH-*, SPEC-REVIEW-*, SAFE-*) and the code-review lens for technical soundness. "
            "Quote evidence verbatim from the ED and cite rule IDs where they apply. "
        ),
    },
]


def _row_to_dict(row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "key": row["key"],
        "label": row["label"],
        "agent_name": row["agent_name"],
        "prompt_context": row["prompt_context"],
        "is_builtin": bool(row["is_builtin"]),
        "created_at": row["created_at"],
    }


class ReviewersDB:
    """Database operations for the reviewer registry."""

    def __init__(self, db):
        self.db = db
        self.ensure_builtins()

    def ensure_builtins(self) -> None:
        """Seed the builtin reviewers. Idempotent (INSERT OR IGNORE)."""
        with self.db.connection() as conn:
            cursor = conn.cursor()
            for r in BUILTIN_REVIEWERS:
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO reviewers (key, label, agent_name, prompt_context, is_builtin)
                    VALUES (?, ?, ?, ?, 1)
                    """,
                    (r["key"], r["label"], r["agent_name"], r["prompt_context"]),
                )

    def list_reviewers(self) -> List[Dict[str, Any]]:
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM reviewers ORDER BY is_builtin DESC, key ASC")
            return [_row_to_dict(row) for row in cursor.fetchall()]

    def get_by_key(self, key: str) -> Optional[Dict[str, Any]]:
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM reviewers WHERE key = ?", (key,))
            row = cursor.fetchone()
            return _row_to_dict(row) if row else None

    def create(self, key: str, label: str, agent_name: str,
               prompt_context: Optional[str] = None) -> Dict[str, Any]:
        if not key or not KEY_PATTERN.match(key):
            raise ValueError("Reviewer key must match ^[a-z0-9_-]{1,32}$")
        if not (label or "").strip():
            raise ValueError("Reviewer label is required")
        if not (agent_name or "").strip():
            raise ValueError("Reviewer agent name is required")
        if self.get_by_key(key):
            raise ValueError(f"Reviewer key already exists: {key}")
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO reviewers (key, label, agent_name, prompt_context, is_builtin)
                VALUES (?, ?, ?, ?, 0)
                """,
                (key, label.strip(), agent_name.strip(), prompt_context),
            )
        return self.get_by_key(key)

    def update(self, key: str, label: Optional[str] = None,
               agent_name: Optional[str] = None,
               prompt_context: Optional[str] = None) -> Dict[str, Any]:
        existing = self.get_by_key(key)
        if not existing:
            raise ValueError(f"Reviewer not found: {key}")
        if agent_name is not None and existing["is_builtin"] and agent_name != existing["agent_name"]:
            raise ValueError("Cannot change the agent name of a builtin reviewer")
        if label is not None and not label.strip():
            raise ValueError("Reviewer label cannot be empty")
        if agent_name is not None and not agent_name.strip():
            raise ValueError("Reviewer agent name cannot be empty")

        new_label = label.strip() if label is not None else existing["label"]
        new_agent = agent_name.strip() if agent_name is not None else existing["agent_name"]
        new_context = prompt_context if prompt_context is not None else existing["prompt_context"]
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE reviewers SET label = ?, agent_name = ?, prompt_context = ? WHERE key = ?",
                (new_label, new_agent, new_context, key),
            )
        return self.get_by_key(key)

    def delete(self, key: str) -> None:
        existing = self.get_by_key(key)
        if not existing:
            raise ValueError(f"Reviewer not found: {key}")
        if existing["is_builtin"]:
            raise ValueError("Cannot delete a builtin reviewer")
        with self.db.connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM reviewers WHERE key = ?", (key,))
