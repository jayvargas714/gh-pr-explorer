from __future__ import annotations
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

    def update_instance_config(self, instance_id: int, config: dict):
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE workflow_instances SET config_json=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE id=?",
                (json.dumps(config), instance_id),
            )

    def save_instance_usage(self, instance_id: int, usage: dict, pr_count: int):
        """Persist aggregate token usage and PR count for a completed run."""
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE workflow_instances SET usage_json=?, pr_count=?, "
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (json.dumps(usage), pr_count, instance_id),
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

    def save_step_outputs(self, instance_id: int, step_id: str, outputs: dict):
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE instance_steps SET outputs_json=? "
                "WHERE instance_id=? AND step_id=?",
                (json.dumps(outputs), instance_id, step_id),
            )

    def save_gate_payload(self, instance_id: int, step_id: str, payload: dict):
        self.save_step_outputs(instance_id, step_id, payload)

    def reset_steps(self, instance_id: int, step_ids: list[str]):
        """Reset steps to pending, clearing outputs and errors."""
        with self.db.connection() as conn:
            for sid in step_ids:
                conn.execute(
                    "UPDATE instance_steps SET status='pending', outputs_json=NULL, "
                    "error_message=NULL, started_at=NULL, completed_at=NULL "
                    "WHERE instance_id=? AND step_id=?",
                    (instance_id, sid),
                )
                conn.execute(
                    "DELETE FROM instance_artifacts WHERE instance_id=? AND step_id=?",
                    (instance_id, sid),
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

    # --- Expert Domains ---

    def list_expert_domains(self, active_only: bool = True,
                            repo: Optional[str] = None) -> list[dict]:
        with self.db.connection() as conn:
            conditions = []
            params: list = []
            if active_only:
                conditions.append("is_active=1")
            if repo is not None:
                conditions.append("repo=?")
                params.append(repo)
            where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
            rows = conn.execute(
                f"SELECT * FROM expert_domains{where} ORDER BY domain_id",
                params,
            ).fetchall()
            results = []
            for r in rows:
                d = dict(r)
                d["triggers"] = json.loads(d.get("triggers_json") or "{}")
                d["checklist"] = json.loads(d.get("checklist_json") or "[]")
                d["anti_patterns"] = json.loads(d.get("anti_patterns_json") or "[]")
                results.append(d)
            return results

    def insert_ai_expert_domains(self, repo: str, experts: list[dict]) -> list[int]:
        """Insert AI-generated expert domains for a specific repo.

        Each expert dict should have: domain_id, display_name, persona, scope,
        checklist, anti_patterns. Triggers are left empty for AI-generated domains.
        Returns a list of inserted row IDs.
        """
        ids = []
        with self.db.connection() as conn:
            for expert in experts:
                domain_id = f"{repo.replace('/', '-')}-{expert['domain_id']}"
                existing = conn.execute(
                    "SELECT id FROM expert_domains WHERE domain_id=?", (domain_id,)
                ).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE expert_domains SET display_name=?, persona=?, scope=?, "
                        "triggers_json=?, checklist_json=?, anti_patterns_json=?, "
                        "is_active=1 WHERE domain_id=?",
                        (expert["display_name"], expert["persona"], expert["scope"],
                         json.dumps(expert.get("triggers", {})),
                         json.dumps(expert.get("checklist", [])),
                         json.dumps(expert.get("anti_patterns", [])),
                         domain_id),
                    )
                    ids.append(existing["id"])
                else:
                    cursor = conn.execute(
                        "INSERT INTO expert_domains "
                        "(domain_id, display_name, persona, scope, triggers_json, "
                        "checklist_json, anti_patterns_json, is_builtin, is_active, repo) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, 0, 1, ?)",
                        (domain_id, expert["display_name"], expert["persona"],
                         expert["scope"], json.dumps(expert.get("triggers", {})),
                         json.dumps(expert.get("checklist", [])),
                         json.dumps(expert.get("anti_patterns", [])),
                         repo),
                    )
                    ids.append(cursor.lastrowid)
        return ids

    def get_expert_domain(self, domain_id: str) -> Optional[dict]:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM expert_domains WHERE domain_id=?", (domain_id,)
            ).fetchone()
            if row:
                d = dict(row)
                d["triggers"] = json.loads(d.get("triggers_json") or "{}")
                d["checklist"] = json.loads(d.get("checklist_json") or "[]")
                d["anti_patterns"] = json.loads(d.get("anti_patterns_json") or "[]")
                return d
            return None

    def create_expert_domain(self, domain_id: str, display_name: str, persona: str,
                             scope: str, triggers: dict, checklist: list,
                             anti_patterns: Optional[list] = None,
                             is_builtin: bool = True,
                             repo: Optional[str] = None) -> int:
        with self.db.connection() as conn:
            cursor = conn.execute(
                "INSERT INTO expert_domains "
                "(domain_id, display_name, persona, scope, triggers_json, "
                "checklist_json, anti_patterns_json, is_builtin, repo) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (domain_id, display_name, persona, scope,
                 json.dumps(triggers), json.dumps(checklist),
                 json.dumps(anti_patterns or []), is_builtin, repo),
            )
            return cursor.lastrowid

    def upsert_expert_domain(self, domain_id: str, display_name: str, persona: str,
                             scope: str, triggers: dict, checklist: list,
                             anti_patterns: Optional[list] = None,
                             is_builtin: bool = True,
                             repo: Optional[str] = None) -> int:
        with self.db.connection() as conn:
            existing = conn.execute(
                "SELECT id FROM expert_domains WHERE domain_id=?", (domain_id,)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE expert_domains SET display_name=?, persona=?, scope=?, "
                    "triggers_json=?, checklist_json=?, anti_patterns_json=?, repo=? "
                    "WHERE domain_id=?",
                    (display_name, persona, scope, json.dumps(triggers),
                     json.dumps(checklist), json.dumps(anti_patterns or []),
                     repo, domain_id),
                )
                return existing["id"]
            return self.create_expert_domain(
                domain_id, display_name, persona, scope,
                triggers, checklist, anti_patterns, is_builtin, repo)

    def update_expert_domain(self, domain_id: str, **kwargs):
        sets = []
        params = []
        for key in ("display_name", "persona", "scope", "is_active"):
            if key in kwargs:
                sets.append(f"{key}=?")
                params.append(kwargs[key])
        for key in ("triggers", "checklist", "anti_patterns"):
            if key in kwargs:
                sets.append(f"{key}_json=?")
                params.append(json.dumps(kwargs[key]))
        if not sets:
            return
        params.append(domain_id)
        with self.db.connection() as conn:
            conn.execute(
                f"UPDATE expert_domains SET {', '.join(sets)} WHERE domain_id=?",
                params,
            )

    def delete_expert_domain(self, domain_id: str):
        with self.db.connection() as conn:
            conn.execute(
                "DELETE FROM expert_domains WHERE domain_id=? AND is_builtin=0",
                (domain_id,),
            )

    # --- Follow-ups ---

    def create_followup(self, instance_id: int, pr_number: int, repo: str,
                        source_run_id: int, verdict: str,
                        review_sha: Optional[str] = None) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self.db.connection() as conn:
            cursor = conn.execute(
                "INSERT INTO review_followups "
                "(instance_id, pr_number, repo, source_run_id, verdict, "
                "review_sha, published_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (instance_id, pr_number, repo, source_run_id, verdict,
                 review_sha, now),
            )
            return cursor.lastrowid

    def get_followup(self, followup_id: int) -> Optional[dict]:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM review_followups WHERE id=?", (followup_id,)
            ).fetchone()
            return dict(row) if row else None

    # --- Usage Stats ---

    def get_usage_stats(self) -> list[dict]:
        """Return average token usage per template (only runs with usage data)."""
        with self.db.connection() as conn:
            rows_all = conn.execute("""
                SELECT wt.name AS template_name,
                       wi.usage_json,
                       wi.pr_count
                FROM workflow_instances wi
                JOIN workflow_templates wt ON wi.template_id = wt.id
                WHERE wi.usage_json IS NOT NULL
                  AND wi.status IN ('completed', 'awaiting_gate')
                ORDER BY wt.name
            """).fetchall()

        from collections import defaultdict
        buckets: dict[str, dict] = defaultdict(lambda: {
            "run_count": 0, "total_prs": 0,
            "total_input_tokens": 0, "total_output_tokens": 0,
            "total_cost_usd": 0.0,
        })

        for row in rows_all:
            tname = row["template_name"]
            b = buckets[tname]
            b["run_count"] += 1
            b["total_prs"] += row["pr_count"] or 0
            try:
                usage = json.loads(row["usage_json"])
                b["total_input_tokens"] += usage.get("input_tokens", 0)
                b["total_output_tokens"] += usage.get("output_tokens", 0)
                b["total_cost_usd"] += usage.get("cost_usd", 0)
            except (json.JSONDecodeError, TypeError):
                pass

        result = []
        for tname, b in buckets.items():
            n = b["run_count"]
            prs = b["total_prs"] or n  # fallback if pr_count was 0
            result.append({
                "template_name": tname,
                "run_count": n,
                "total_prs": b["total_prs"],
                "avg_input_tokens_per_run": round(b["total_input_tokens"] / n) if n else 0,
                "avg_output_tokens_per_run": round(b["total_output_tokens"] / n) if n else 0,
                "avg_cost_per_run": round(b["total_cost_usd"] / n, 4) if n else 0,
                "avg_input_tokens_per_pr": round(b["total_input_tokens"] / prs) if prs else 0,
                "avg_output_tokens_per_pr": round(b["total_output_tokens"] / prs) if prs else 0,
                "avg_cost_per_pr": round(b["total_cost_usd"] / prs, 4) if prs else 0,
            })
        return result

    def list_followups(self, repo: Optional[str] = None,
                       status: Optional[str] = None) -> list[dict]:
        conditions = []
        params: list = []
        if repo:
            conditions.append("repo=?")
            params.append(repo)
        if status == "active":
            conditions.append(
                "status NOT IN ('RESOLVED','CONCEDED','MERGED','CLOSED','WONTFIX')"
            )
        elif status:
            conditions.append("status=?")
            params.append(status)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        with self.db.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM review_followups{where} ORDER BY created_at DESC",
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    def update_followup_status(self, followup_id: int, status: str,
                               notes: Optional[str] = None):
        now = datetime.now(timezone.utc).isoformat()
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE review_followups SET status=?, last_checked=?, notes=? "
                "WHERE id=?",
                (status, now, notes, followup_id),
            )

    def create_followup_finding(self, followup_id: int, finding_id: str,
                                original_text: str, severity: str) -> int:
        with self.db.connection() as conn:
            cursor = conn.execute(
                "INSERT INTO followup_findings "
                "(followup_id, finding_id, original_text, severity) "
                "VALUES (?, ?, ?, ?)",
                (followup_id, finding_id, original_text, severity),
            )
            return cursor.lastrowid

    def update_followup_finding(self, finding_id: int, status: str,
                                author_response: Optional[str] = None,
                                resolution_notes: Optional[str] = None):
        now = datetime.now(timezone.utc).isoformat()
        with self.db.connection() as conn:
            conn.execute(
                "UPDATE followup_findings SET status=?, author_response=?, "
                "resolution_notes=?, updated_at=? WHERE id=?",
                (status, author_response, resolution_notes, now, finding_id),
            )

    # --- Code Owners ---

    def upsert_code_owner(self, github_handle: str, display_name: str,
                          priority_boost: int = 0, is_reviewer: bool = True):
        with self.db.connection() as conn:
            existing = conn.execute(
                "SELECT id FROM code_owner_registry WHERE github_handle=?",
                (github_handle,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    "INSERT INTO code_owner_registry "
                    "(github_handle, display_name, priority_boost, is_reviewer) "
                    "VALUES (?, ?, ?, ?)",
                    (github_handle, display_name, priority_boost, is_reviewer),
                )

    def get_followup_findings(self, followup_id: int) -> list[dict]:
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM followup_findings WHERE followup_id=? ORDER BY id",
                (followup_id,),
            ).fetchall()
            return [dict(r) for r in rows]
