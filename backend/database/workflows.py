"""DB access layer for workflow engine tables."""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from backend.database.base import Database

logger = logging.getLogger(__name__)


class WorkflowDB:
    """CRUD operations for workflow templates, instances, steps, and artifacts."""

    def __init__(self, db: Database):
        self.db = db

    # --- Templates ---

    def list_templates(self) -> list[dict]:
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT id, name, description, is_builtin, created_at, updated_at "
                "FROM workflow_templates ORDER BY is_builtin DESC, name"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_template(self, template_id: int) -> Optional[dict]:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_templates WHERE id = ?", (template_id,)
            ).fetchone()
            if row:
                result = dict(row)
                result["template"] = json.loads(result["template_json"])
                return result
            return None

    def get_template_by_name(self, name: str) -> Optional[dict]:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_templates WHERE name = ?", (name,)
            ).fetchone()
            if row:
                result = dict(row)
                result["template"] = json.loads(result["template_json"])
                return result
            return None

    def create_template(self, name: str, description: str, template_json: dict,
                        is_builtin: bool = False) -> int:
        with self.db.connection() as conn:
            cursor = conn.execute(
                "INSERT INTO workflow_templates (name, description, template_json, is_builtin) "
                "VALUES (?, ?, ?, ?)",
                (name, description, json.dumps(template_json), is_builtin),
            )
            return cursor.lastrowid

    def update_template(self, template_id: int, name: str, description: str,
                        template_json: dict):
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE workflow_templates SET name=?, description=?, template_json=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE id=? AND is_builtin=0",
                (name, description, json.dumps(template_json), template_id),
            )

    def delete_template(self, template_id: int):
        with self.db.connection() as conn:
            conn.execute(
                "DELETE FROM workflow_templates WHERE id=? AND is_builtin=0",
                (template_id,),
            )

    # --- Instances ---

    def create_instance(self, template_id: int, repo: str, status: str = "pending",
                        config_json: Optional[dict] = None) -> int:
        with self.db.connection() as conn:
            cursor = conn.execute(
                "INSERT INTO workflow_instances (template_id, repo, status, config_json) "
                "VALUES (?, ?, ?, ?)",
                (template_id, repo, status, json.dumps(config_json or {})),
            )
            return cursor.lastrowid

    def get_instance(self, instance_id: int) -> Optional[dict]:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT wi.*, wt.name as template_name, wt.description as template_description "
                "FROM workflow_instances wi "
                "JOIN workflow_templates wt ON wi.template_id = wt.id "
                "WHERE wi.id = ?", (instance_id,)
            ).fetchone()
            if row:
                result = dict(row)
                result["config"] = json.loads(result.get("config_json") or "{}")
                return result
            return None

    def list_instances(self, repo: Optional[str] = None, limit: int = 50) -> list[dict]:
        with self.db.connection() as conn:
            if repo:
                rows = conn.execute(
                    "SELECT wi.*, wt.name as template_name "
                    "FROM workflow_instances wi "
                    "JOIN workflow_templates wt ON wi.template_id = wt.id "
                    "WHERE wi.repo = ? ORDER BY wi.created_at DESC LIMIT ?",
                    (repo, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT wi.*, wt.name as template_name "
                    "FROM workflow_instances wi "
                    "JOIN workflow_templates wt ON wi.template_id = wt.id "
                    "ORDER BY wi.created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    def update_instance_status(self, instance_id: int, status: str):
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE workflow_instances SET status=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE id=?", (status, instance_id),
            )

    # --- Steps ---

    def create_step(self, instance_id: int, step_id: str, step_type: str,
                    step_config: dict, agent_id: Optional[int] = None) -> int:
        with self.db.connection() as conn:
            cursor = conn.execute(
                "INSERT INTO instance_steps "
                "(instance_id, step_id, step_type, step_config_json, status, agent_id) "
                "VALUES (?, ?, ?, ?, 'pending', ?)",
                (instance_id, step_id, step_type, json.dumps(step_config), agent_id),
            )
            return cursor.lastrowid

    def update_step_status(self, instance_id: int, step_id: str, status: str,
                           error: Optional[str] = None):
        now = datetime.now(timezone.utc).isoformat()
        with self.db.connection() as conn:
            if status == "running":
                conn.execute(
                    "UPDATE instance_steps SET status=?, started_at=? "
                    "WHERE instance_id=? AND step_id=?",
                    (status, now, instance_id, step_id),
                )
            elif status in ("completed", "failed", "awaiting_gate"):
                conn.execute(
                    "UPDATE instance_steps SET status=?, completed_at=?, error_message=? "
                    "WHERE instance_id=? AND step_id=?",
                    (status, now, error, instance_id, step_id),
                )
            else:
                conn.execute(
                    "UPDATE instance_steps SET status=? WHERE instance_id=? AND step_id=?",
                    (status, instance_id, step_id),
                )

    def get_steps(self, instance_id: int) -> list[dict]:
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM instance_steps WHERE instance_id=? ORDER BY id",
                (instance_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # --- Artifacts ---

    def save_artifact(self, instance_id: int, step_id: str, artifact: dict) -> int:
        with self.db.connection() as conn:
            cursor = conn.execute(
                "INSERT INTO instance_artifacts "
                "(instance_id, step_id, pr_number, artifact_type, file_path, content_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    instance_id,
                    step_id,
                    artifact.get("pr_number"),
                    artifact.get("type", "unknown"),
                    artifact.get("file_path"),
                    json.dumps(artifact.get("data")) if artifact.get("data") else None,
                ),
            )
            return cursor.lastrowid

    def get_artifacts(self, instance_id: int, step_id: Optional[str] = None) -> list[dict]:
        with self.db.connection() as conn:
            if step_id:
                rows = conn.execute(
                    "SELECT * FROM instance_artifacts WHERE instance_id=? AND step_id=?",
                    (instance_id, step_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM instance_artifacts WHERE instance_id=?",
                    (instance_id,),
                ).fetchall()
            return [dict(r) for r in rows]

    def save_gate_payload(self, instance_id: int, step_id: str, payload: dict):
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE instance_steps SET outputs_json=? "
                "WHERE instance_id=? AND step_id=?",
                (json.dumps(payload), instance_id, step_id),
            )

    # --- Agents ---

    def list_agents(self) -> list[dict]:
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM agents WHERE is_active=1 ORDER BY name"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_agent(self, agent_id: int) -> Optional[dict]:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone()
            return dict(row) if row else None

    def create_agent(self, name: str, agent_type: str, model: str,
                     config_json: Optional[dict] = None) -> int:
        with self.db.connection() as conn:
            cursor = conn.execute(
                "INSERT INTO agents (name, type, model, config_json) VALUES (?, ?, ?, ?)",
                (name, agent_type, model, json.dumps(config_json or {})),
            )
            return cursor.lastrowid

    def upsert_agent(self, name: str, agent_type: str, model: str,
                     config_json: Optional[dict] = None) -> int:
        with self.db.connection() as conn:
            existing = conn.execute(
                "SELECT id FROM agents WHERE name=?", (name,)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE agents SET type=?, model=?, config_json=?, updated_at=CURRENT_TIMESTAMP "
                    "WHERE name=?",
                    (agent_type, model, json.dumps(config_json or {}), name),
                )
                return existing["id"]
            cursor = conn.execute(
                "INSERT INTO agents (name, type, model, config_json) VALUES (?, ?, ?, ?)",
                (name, agent_type, model, json.dumps(config_json or {})),
            )
            return cursor.lastrowid
