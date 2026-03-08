"""API routes for the generic workflow engine."""

import json
import logging
import threading

from flask import Blueprint, request, jsonify

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
        db.update_instance_status(instance_id, "cancelled")
        return jsonify({"ok": True, "status": "cancelled"})

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
