"""API routes for the generic workflow engine."""

import json
import logging
import threading

from flask import Blueprint, request, jsonify, Response

from backend.database import get_workflow_db
from backend.workflows.runtime import WorkflowRuntime, validate_template

logger = logging.getLogger(__name__)

workflow_engine_bp = Blueprint("workflow_engine", __name__)


@workflow_engine_bp.route("/api/templates", methods=["GET"])
def list_templates():
    db = get_workflow_db()
    templates = db.list_templates()
    return jsonify(templates)


@workflow_engine_bp.route("/api/templates/<int:template_id>", methods=["GET"])
def get_template(template_id):
    db = get_workflow_db()
    template = db.get_template(template_id)
    if not template:
        return jsonify({"error": "Template not found"}), 404
    return jsonify(template)


@workflow_engine_bp.route("/api/templates", methods=["POST"])
def create_template():
    data = request.get_json()
    if not data or "name" not in data or "template" not in data:
        return jsonify({"error": "name and template are required"}), 400

    errors = validate_template(data["template"])
    if errors:
        return jsonify({"error": "Invalid template", "validation_errors": errors}), 400

    db = get_workflow_db()
    template_id = db.create_template(
        name=data["name"],
        description=data.get("description", ""),
        template_json=data["template"],
    )
    return jsonify({"id": template_id}), 201


@workflow_engine_bp.route("/api/templates/<int:template_id>", methods=["PUT"])
def update_template(template_id):
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body required"}), 400

    db = get_workflow_db()
    existing = db.get_template(template_id)
    if not existing:
        return jsonify({"error": "Template not found"}), 404
    if existing.get("is_builtin"):
        return jsonify({"error": "Cannot edit built-in templates. Clone first."}), 403

    if "template" in data:
        errors = validate_template(data["template"])
        if errors:
            return jsonify({"error": "Invalid template", "validation_errors": errors}), 400

    db.update_template(
        template_id,
        name=data.get("name", existing["name"]),
        description=data.get("description", existing.get("description", "")),
        template_json=data.get("template", existing["template"]),
    )
    return jsonify({"ok": True})


@workflow_engine_bp.route("/api/templates/<int:template_id>/clone", methods=["POST"])
def clone_template(template_id):
    db = get_workflow_db()
    existing = db.get_template(template_id)
    if not existing:
        return jsonify({"error": "Template not found"}), 404

    data = request.get_json() or {}
    new_name = data.get("name", f"{existing['name']} (copy)")

    new_id = db.create_template(
        name=new_name,
        description=existing.get("description", ""),
        template_json=existing["template"],
    )
    return jsonify({"id": new_id}), 201


@workflow_engine_bp.route("/api/templates/<int:template_id>/validate", methods=["POST"])
def validate_template_endpoint(template_id):
    db = get_workflow_db()
    existing = db.get_template(template_id)
    if not existing:
        return jsonify({"error": "Template not found"}), 404

    errors = validate_template(existing["template"])
    return jsonify({"valid": len(errors) == 0, "errors": errors})


@workflow_engine_bp.route("/api/templates/<int:template_id>", methods=["DELETE"])
def delete_template(template_id):
    db = get_workflow_db()
    existing = db.get_template(template_id)
    if not existing:
        return jsonify({"error": "Template not found"}), 404
    if existing.get("is_builtin"):
        return jsonify({"error": "Cannot delete built-in templates"}), 403
    db.delete_template(template_id)
    return jsonify({"ok": True})


# --- Workflow Instances ---

@workflow_engine_bp.route("/api/workflows/run", methods=["POST"])
def create_instance():
    data = request.get_json()
    if not data or "template_id" not in data:
        return jsonify({"error": "template_id is required"}), 400

    db = get_workflow_db()
    template = db.get_template(data["template_id"])
    if not template:
        return jsonify({"error": "Template not found"}), 404

    repo = data.get("repo", "")
    config = data.get("config", {})

    instance_id = db.create_instance(
        template_id=data["template_id"],
        repo=repo,
        status="pending",
        config_json=config,
    )

    step_overrides = config.get("step_overrides", {})
    agent_overrides = config.get("agent_overrides", {})
    for step in template["template"].get("steps", []):
        step_config = dict(step.get("config", {}))
        if step["id"] in step_overrides:
            step_config.update(step_overrides[step["id"]])
        if step["id"] in agent_overrides:
            step_config["agent"] = agent_overrides[step["id"]]
        db.create_step(
            instance_id=instance_id,
            step_id=step["id"],
            step_type=step["type"],
            step_config=step_config,
        )

    # Ensure executors are registered
    import backend.workflows.executors  # noqa: F401

    thread = threading.Thread(
        target=_run_workflow,
        args=(instance_id, template["template"], repo, config),
        daemon=True,
    )
    thread.start()

    return jsonify({"id": instance_id, "status": "pending"}), 201


@workflow_engine_bp.route("/api/workflows/instances", methods=["GET"])
def list_instances():
    db = get_workflow_db()
    repo = request.args.get("repo")
    instances = db.list_instances(repo=repo)
    return jsonify(instances)


@workflow_engine_bp.route("/api/workflows/instances/<int:instance_id>", methods=["GET"])
def get_instance(instance_id):
    db = get_workflow_db()
    instance = db.get_instance(instance_id)
    if not instance:
        return jsonify({"error": "Instance not found"}), 404

    steps = db.get_steps(instance_id)
    artifacts = db.get_artifacts(instance_id)

    instance["steps"] = steps
    instance["artifacts"] = artifacts
    return jsonify(instance)


@workflow_engine_bp.route("/api/workflows/instances/<int:instance_id>/gate", methods=["POST"])
def gate_action(instance_id):
    db = get_workflow_db()
    instance = db.get_instance(instance_id)
    if not instance:
        return jsonify({"error": "Instance not found"}), 404
    if instance["status"] != "awaiting_gate":
        return jsonify({"error": f"Instance is not awaiting gate (status: {instance['status']})"}), 400

    data = request.get_json() or {}
    action = data.get("action", "approve")

    if action == "reject":
        reason = data.get("reason", "Rejected by user")
        steps = db.get_steps(instance_id)
        for step in steps:
            if step["status"] == "awaiting_gate":
                db.update_step_status(instance_id, step["step_id"], "failed",
                                      error=f"Gate rejected: {reason}")
            elif step["status"] == "running":
                db.update_step_status(instance_id, step["step_id"], "failed",
                                      error="Cancelled: workflow rejected")
        db.update_instance_status(instance_id, "cancelled")
        return jsonify({"ok": True, "status": "cancelled", "reason": reason})

    template_data = db.get_template(instance["template_id"])
    if not template_data:
        return jsonify({"error": "Template not found"}), 500

    db.update_instance_status(instance_id, "running")

    thread = threading.Thread(
        target=_resume_workflow,
        args=(instance_id, template_data["template"], instance, data),
        daemon=True,
    )
    thread.start()

    return jsonify({"ok": True, "status": "running"})


@workflow_engine_bp.route("/api/workflows/instances/<int:instance_id>", methods=["DELETE"])
def cancel_instance(instance_id):
    db = get_workflow_db()
    instance = db.get_instance(instance_id)
    if not instance:
        return jsonify({"error": "Instance not found"}), 404
    db.update_instance_status(instance_id, "cancelled")
    return jsonify({"ok": True})


@workflow_engine_bp.route("/api/workflows/instances/<int:instance_id>/steps/<step_id>/live", methods=["GET"])
def get_step_live_output(instance_id, step_id):
    from backend.workflows.executors.agent_review import get_agent_live_output
    text = get_agent_live_output(instance_id, step_id)
    return jsonify({"output": text})


@workflow_engine_bp.route("/api/workflows/instances/<int:instance_id>/steps/<step_id>/retry", methods=["POST"])
def retry_step(instance_id, step_id):
    """Retry a workflow from a given step, re-executing it and all downstream steps."""
    db = get_workflow_db()
    instance = db.get_instance(instance_id)
    if not instance:
        return jsonify({"error": "Instance not found"}), 404

    steps = db.get_steps(instance_id)
    target = next((s for s in steps if s["step_id"] == step_id), None)
    if not target:
        return jsonify({"error": f"Step '{step_id}' not found"}), 404

    if target["status"] == "running":
        return jsonify({"error": "Step is currently running"}), 400

    template_data = db.get_template(instance["template_id"])
    if not template_data:
        return jsonify({"error": "Template not found"}), 500

    db.update_instance_status(instance_id, "running")

    thread = threading.Thread(
        target=_retry_from_step,
        args=(instance_id, template_data["template"], instance, step_id),
        daemon=True,
    )
    thread.start()

    return jsonify({"ok": True, "status": "running", "retrying_from": step_id})


# --- Agents ---

@workflow_engine_bp.route("/api/agents", methods=["GET"])
def list_agents():
    db = get_workflow_db()
    agents = db.list_agents()
    return jsonify(agents)


@workflow_engine_bp.route("/api/step-types", methods=["GET"])
def list_step_types():
    import backend.workflows.executors  # noqa: F401
    from backend.workflows.step_types import STEP_REGISTRY
    return jsonify({"available": list(STEP_REGISTRY.keys())})


# --- Expert Domains ---

@workflow_engine_bp.route("/api/expert-domains", methods=["GET"])
def list_expert_domains():
    db = get_workflow_db()
    active_only = request.args.get("active_only", "true").lower() != "false"
    domains = db.list_expert_domains(active_only=active_only)
    return jsonify(domains)


@workflow_engine_bp.route("/api/expert-domains", methods=["POST"])
def create_expert_domain():
    data = request.get_json()
    if not data or "domain_id" not in data:
        return jsonify({"error": "domain_id is required"}), 400
    db = get_workflow_db()
    try:
        domain_id = db.create_expert_domain(
            domain_id=data["domain_id"],
            display_name=data.get("display_name", data["domain_id"]),
            persona=data.get("persona", ""),
            scope=data.get("scope", ""),
            triggers=data.get("triggers", {"file_patterns": [], "keywords": []}),
            checklist=data.get("checklist", []),
            anti_patterns=data.get("anti_patterns", []),
            is_builtin=False,
        )
        return jsonify({"id": domain_id}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@workflow_engine_bp.route("/api/expert-domains/<domain_id>", methods=["PUT"])
def update_expert_domain(domain_id):
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body required"}), 400
    db = get_workflow_db()
    existing = db.get_expert_domain(domain_id)
    if not existing:
        return jsonify({"error": "Domain not found"}), 404
    db.update_expert_domain(domain_id, **data)
    return jsonify({"ok": True})


@workflow_engine_bp.route("/api/expert-domains/<domain_id>", methods=["DELETE"])
def delete_expert_domain(domain_id):
    db = get_workflow_db()
    existing = db.get_expert_domain(domain_id)
    if not existing:
        return jsonify({"error": "Domain not found"}), 404
    if existing.get("is_builtin"):
        return jsonify({"error": "Cannot delete built-in domains"}), 403
    db.delete_expert_domain(domain_id)
    return jsonify({"ok": True})


# --- Follow-ups ---

@workflow_engine_bp.route("/api/followups", methods=["GET"])
def list_followups():
    db = get_workflow_db()
    repo = request.args.get("repo")
    status = request.args.get("status")
    followups = db.list_followups(repo=repo, status=status)
    for fu in followups:
        fu["findings"] = db.get_followup_findings(fu["id"])
    return jsonify(followups)


@workflow_engine_bp.route("/api/followups/<int:followup_id>", methods=["GET"])
def get_followup(followup_id):
    db = get_workflow_db()
    fu = db.get_followup(followup_id)
    if not fu:
        return jsonify({"error": "Follow-up not found"}), 404
    fu["findings"] = db.get_followup_findings(followup_id)
    return jsonify(fu)


# --- Background execution ---

def _run_workflow(instance_id: int, template: dict, repo: str, config: dict):
    db = get_workflow_db()
    db.update_instance_status(instance_id, "running")
    try:
        runtime = WorkflowRuntime(template, instance_id, db_accessor=db)
        result = runtime.execute(
            initial_inputs={"repo": repo},
            instance_config={"repo": repo, **config},
        )
        db.update_instance_status(instance_id, result["status"])
    except Exception as e:
        logger.error(f"Workflow instance {instance_id} failed: {e}")
        db.update_instance_status(instance_id, "failed")


def _resume_workflow(instance_id: int, template: dict, instance: dict, gate_decision: dict):
    db = get_workflow_db()
    try:
        steps = db.get_steps(instance_id)
        gate_step = next(
            (s for s in steps if s["status"] == "awaiting_gate"),
            None,
        )
        if not gate_step:
            db.update_instance_status(instance_id, "failed")
            return

        all_outputs = {"repo": instance.get("repo", "")}
        for s in steps:
            if s["status"] == "completed" and s.get("outputs_json"):
                try:
                    step_out = json.loads(s["outputs_json"])
                    all_outputs.update(step_out)
                except (json.JSONDecodeError, TypeError):
                    pass

        runtime = WorkflowRuntime(template, instance_id, db_accessor=db)
        config = json.loads(instance.get("config_json") or "{}")
        result = runtime.resume_after_gate(
            gate_step_id=gate_step["step_id"],
            gate_decision=gate_decision,
            all_outputs=all_outputs,
            instance_config={"repo": instance.get("repo", ""), **config},
        )
        db.update_instance_status(instance_id, result["status"])
    except Exception as e:
        logger.error(f"Workflow resume for instance {instance_id} failed: {e}")
        db.update_instance_status(instance_id, "failed")


def _retry_from_step(instance_id: int, template: dict, instance: dict, step_id: str):
    db = get_workflow_db()
    try:
        steps = db.get_steps(instance_id)

        all_outputs = {"repo": instance.get("repo", "")}
        runtime = WorkflowRuntime(template, instance_id, db_accessor=db)
        downstream = runtime._get_downstream_inclusive(step_id)

        for s in steps:
            if s["status"] == "completed" and s["step_id"] not in downstream and s.get("outputs_json"):
                try:
                    step_out = json.loads(s["outputs_json"])
                    all_outputs.update(step_out)
                except (json.JSONDecodeError, TypeError):
                    pass

        config = json.loads(instance.get("config_json") or "{}")
        result = runtime.retry_from_step(
            retry_step_id=step_id,
            all_outputs=all_outputs,
            instance_config={"repo": instance.get("repo", ""), **config},
        )
        db.update_instance_status(instance_id, result["status"])
    except Exception as e:
        logger.error(f"Workflow retry from {step_id} for instance {instance_id} failed: {e}")
        db.update_instance_status(instance_id, "failed")


@workflow_engine_bp.route(
    "/api/workflows/instances/<int:instance_id>/steps/<step_id>/download", methods=["GET"]
)
def download_step_output(instance_id, step_id):
    fmt = request.args.get("format", "md")
    db = get_workflow_db()
    steps = db.get_steps(instance_id)
    step = next((s for s in steps if s["step_id"] == step_id), None)
    if not step:
        return jsonify({"error": "Step not found"}), 404
    if not step.get("outputs_json"):
        return jsonify({"error": "No output available"}), 404

    outputs = json.loads(step["outputs_json"])
    step_type = step["step_type"]

    WRAPPER_KEYS = {
        "synthesis": "synthesis",
        "holistic_review": "holistic",
    }
    wrapper = WRAPPER_KEYS.get(step_type)
    if wrapper and wrapper in outputs and isinstance(outputs[wrapper], dict):
        outputs = outputs[wrapper]

    if fmt == "json":
        content = json.dumps(outputs, indent=2)
        mime = "application/json"
        ext = "json"
    else:
        content = _outputs_to_markdown(outputs, step_type, step_id, instance_id)
        mime = "text/markdown"
        ext = "md"

    filename = f"run-{instance_id}-{step_id}.{ext}"
    return Response(
        content,
        mimetype=mime,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _outputs_to_markdown(outputs: dict, step_type: str, step_id: str, instance_id: int) -> str:
    lines = [f"# {step_type.replace('_', ' ').title()} — Run #{instance_id}, Step: {step_id}\n"]

    if step_type in ("synthesis", "holistic_review"):
        verdict = outputs.get("verdict", "N/A")
        summary = outputs.get("summary", "")
        lines.append(f"## Verdict: {verdict}\n")
        if summary:
            lines.append(f"{summary}\n")

        for section_key, label in [
            ("blocking_findings", "Blocking Findings"),
            ("non_blocking_findings", "Non-Blocking Findings"),
            ("agreed", "Agreed Findings"),
            ("a_only", "Agent A Only"),
            ("b_only", "Agent B Only"),
            ("cross_cutting_findings", "Cross-Cutting Findings"),
            ("synth_findings", "SYNTH Findings"),
        ]:
            items = outputs.get(section_key, [])
            if not items:
                continue
            lines.append(f"## {label} ({len(items)})\n")
            for i, item in enumerate(items, 1):
                if isinstance(item, dict):
                    title = item.get("title", item.get("finding", {}).get("title", f"Finding {i}"))
                    severity = item.get("severity", "")
                    desc = item.get("description", item.get("problem", ""))
                    sev_tag = f" [{severity}]" if severity else ""
                    lines.append(f"{i}. **{title}**{sev_tag}")
                    if desc:
                        lines.append(f"   {desc}\n")
                elif isinstance(item, str):
                    lines.append(f"{i}. {item}")

        per_domain = outputs.get("per_domain_synthesis", [])
        if per_domain:
            lines.append(f"## Per-Domain Synthesis ({len(per_domain)} domains)\n")
            for ds in per_domain:
                if isinstance(ds, dict):
                    domain = ds.get("domain", "?")
                    dv = ds.get("verdict", "?")
                    tf = ds.get("total_findings", 0)
                    lines.append(f"### {domain} — {dv} ({tf} findings)\n")

        questions = outputs.get("questions", [])
        if questions:
            lines.append(f"## Questions ({len(questions)})\n")
            for i, q in enumerate(questions, 1):
                lines.append(f"{i}. {q}")

    elif step_type == "agent_review":
        reviews = outputs.get("reviews", [])
        for r in reviews:
            if isinstance(r, dict):
                domain = r.get("domain", "general")
                agent = r.get("agent_name", "?")
                lines.append(f"## Review: {domain} (by {agent})\n")
                content = r.get("content", r.get("review_text", ""))
                if content:
                    lines.append(content)
                    lines.append("")

    else:
        lines.append("```json")
        lines.append(json.dumps(outputs, indent=2))
        lines.append("```")

    return "\n".join(lines)
