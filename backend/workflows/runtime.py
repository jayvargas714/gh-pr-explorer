"""WorkflowRuntime — executes a workflow template as an instance.

Walks the step graph in topological order, dispatches to executors,
handles fan-out/fan-in parallelism, and pauses at human gates.
"""

import json
import logging
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Optional

from backend.workflows.step_types import get_executor_class
from backend.workflows.executor import StepResult

logger = logging.getLogger(__name__)


class WorkflowRuntime:
    """Executes a workflow template against a set of inputs."""

    def __init__(self, template: dict, instance_id: int, db_accessor=None):
        self.template = template
        self.instance_id = instance_id
        self.db = db_accessor
        self.steps = {s["id"]: s for s in template.get("steps", [])}
        self.edges = template.get("edges", [])
        self.fan_out_groups = template.get("fan_out_groups", [])
        self._overlay_db_step_configs()

    def execute(self, initial_inputs: dict, instance_config: dict) -> dict:
        """Run the workflow from start to finish (or until a gate pause).

        Returns a dict with:
          - status: 'completed' | 'awaiting_gate' | 'failed'
          - outputs: merged outputs from all completed steps
          - gate_step_id: if paused at a gate, the step that requires human input
          - error: if failed
        """
        missing = self._check_executors()
        if missing:
            error_msg = (
                f"Cannot run workflow: missing executors for step types: "
                f"{', '.join(missing)}. These are Phase 3+ features not yet implemented."
            )
            logger.error(error_msg)
            for step_id, step_def in self.steps.items():
                if step_def["type"] in missing:
                    self._update_step_status(step_id, "failed", error=error_msg)
            return {"status": "failed", "outputs": {}, "error": error_msg}

        levels = self._parallel_levels()
        step_outputs: dict[str, dict] = {}
        all_outputs = dict(initial_inputs)

        for level in levels:
            if len(level) == 1:
                result = self._execute_single_step(
                    level[0], step_outputs, all_outputs, instance_config
                )
                if result is not None:
                    return result
            else:
                result = self._execute_parallel_steps(
                    level, step_outputs, all_outputs, instance_config
                )
                if result is not None:
                    return result

        return {"status": "completed", "outputs": all_outputs}

    def _execute_single_step(self, step_id: str, step_outputs: dict,
                              all_outputs: dict, instance_config: dict) -> Optional[dict]:
        """Run one step. Returns a result dict if the workflow should stop, else None."""
        step_def = self.steps[step_id]
        step_type = step_def["type"]
        step_config = step_def.get("config", {})

        upstream_ids = self._get_upstream(step_id)
        inputs = dict(all_outputs)
        for uid in upstream_ids:
            if uid in step_outputs:
                self._merge_outputs(inputs, step_outputs[uid])

        self._update_step_status(step_id, "running")

        try:
            executor_cls = get_executor_class(step_type)
            enriched_config = {**step_config, "_step_id": step_id}
            enriched_inst = {**instance_config, "_instance_id": self.instance_id}
            executor = executor_cls(step_config=enriched_config, instance_config=enriched_inst)
            result = executor.execute(inputs)
        except Exception as e:
            logger.error(f"Step {step_id} ({step_type}) failed: {e}")
            self._update_step_status(step_id, "failed", error=str(e))
            return {"status": "failed", "outputs": all_outputs, "error": str(e)}

        if not result.success:
            self._update_step_status(step_id, "failed", error=result.error)
            return {"status": "failed", "outputs": all_outputs, "error": result.error}

        if result.awaiting_gate:
            self._update_step_status(step_id, "awaiting_gate")
            self._save_gate_payload(step_id, result.gate_payload)
            return {
                "status": "awaiting_gate",
                "outputs": all_outputs,
                "gate_step_id": step_id,
                "gate_payload": result.gate_payload,
            }

        step_outputs[step_id] = result.outputs
        all_outputs.update(result.outputs)
        self._update_step_status(step_id, "completed")
        self._save_step_outputs(step_id, result.outputs)

        for artifact in result.artifacts:
            self._save_artifact(step_id, artifact)

        return None

    def _execute_parallel_steps(self, step_ids: list[str], step_outputs: dict,
                                 all_outputs: dict, instance_config: dict) -> Optional[dict]:
        """Run multiple steps concurrently. Returns a result dict if workflow should stop, else None."""
        logger.info(f"Running {len(step_ids)} steps in parallel: {step_ids}")

        per_step_inputs = {}
        for step_id in step_ids:
            upstream_ids = self._get_upstream(step_id)
            inputs = dict(all_outputs)
            for uid in upstream_ids:
                if uid in step_outputs:
                    self._merge_outputs(inputs, step_outputs[uid])
            per_step_inputs[step_id] = inputs

        for sid in step_ids:
            self._update_step_status(sid, "running")

        futures = {}
        with ThreadPoolExecutor(max_workers=len(step_ids)) as pool:
            for step_id in step_ids:
                step_def = self.steps[step_id]
                step_type = step_def["type"]
                step_config = step_def.get("config", {})

                executor_cls = get_executor_class(step_type)
                enriched_config = {**step_config, "_step_id": step_id}
                enriched_inst = {**instance_config, "_instance_id": self.instance_id}
                executor = executor_cls(step_config=enriched_config, instance_config=enriched_inst)

                future = pool.submit(executor.execute, per_step_inputs[step_id])
                futures[future] = step_id

            for future in as_completed(futures):
                step_id = futures[future]
                step_type = self.steps[step_id]["type"]
                try:
                    result = future.result()
                except Exception as e:
                    logger.error(f"Step {step_id} ({step_type}) failed: {e}")
                    self._update_step_status(step_id, "failed", error=str(e))
                    return {"status": "failed", "outputs": all_outputs, "error": str(e)}

                if not result.success:
                    self._update_step_status(step_id, "failed", error=result.error)
                    return {"status": "failed", "outputs": all_outputs, "error": result.error}

                if result.awaiting_gate:
                    self._update_step_status(step_id, "awaiting_gate")
                    self._save_gate_payload(step_id, result.gate_payload)
                    return {
                        "status": "awaiting_gate", "outputs": all_outputs,
                        "gate_step_id": step_id, "gate_payload": result.gate_payload,
                    }

                step_outputs[step_id] = result.outputs
                self._merge_outputs(all_outputs, result.outputs)
                self._update_step_status(step_id, "completed")
                self._save_step_outputs(step_id, result.outputs)

                for artifact in result.artifacts:
                    self._save_artifact(step_id, artifact)

        return None

    def execute_fan_out(self, step_id: str, items: list, inputs: dict, instance_config: dict,
                        max_parallel: int = 4) -> list[StepResult]:
        """Execute a step N times in parallel (one per item in the fan-out list).

        Returns a list of StepResults, one per item.
        """
        step_def = self.steps[step_id]
        step_type = step_def["type"]
        step_config = step_def.get("config", {})

        results = []
        with ThreadPoolExecutor(max_workers=max_parallel) as pool:
            futures = {}
            for i, item in enumerate(items):
                item_inputs = dict(inputs)
                item_inputs["fan_out_item"] = item
                item_inputs["fan_out_index"] = i

                executor_cls = get_executor_class(step_type)
                executor = executor_cls(step_config=step_config, instance_config=instance_config)
                future = pool.submit(executor.execute, item_inputs)
                futures[future] = i

            for future in as_completed(futures):
                idx = futures[future]
                try:
                    result = future.result()
                except Exception as e:
                    result = StepResult(success=False, error=str(e))
                results.append((idx, result))

        results.sort(key=lambda x: x[0])
        return [r for _, r in results]

    def resume_after_gate(self, gate_step_id: str, gate_decision: dict,
                          all_outputs: dict, instance_config: dict) -> dict:
        """Resume execution after a human gate decision.

        Continues from the step after the gate.
        """
        all_outputs.update(gate_decision)
        topo_order = self._topological_sort()

        past_gate = False
        for step_id in topo_order:
            if step_id == gate_step_id:
                self._update_step_status(step_id, "completed")
                past_gate = True
                continue
            if not past_gate:
                continue

            step_def = self.steps[step_id]
            step_type = step_def["type"]
            step_config = step_def.get("config", {})

            try:
                executor_cls = get_executor_class(step_type)
                enriched_config = {**step_config, "_step_id": step_id}
                enriched_inst = {**instance_config, "_instance_id": self.instance_id}
                executor = executor_cls(step_config=enriched_config, instance_config=enriched_inst)
                result = executor.execute(all_outputs)
            except Exception as e:
                self._update_step_status(step_id, "failed", error=str(e))
                return {"status": "failed", "outputs": all_outputs, "error": str(e)}

            if not result.success:
                self._update_step_status(step_id, "failed", error=result.error)
                return {"status": "failed", "outputs": all_outputs, "error": result.error}

            if result.awaiting_gate:
                self._update_step_status(step_id, "awaiting_gate")
                return {
                    "status": "awaiting_gate",
                    "outputs": all_outputs,
                    "gate_step_id": step_id,
                    "gate_payload": result.gate_payload,
                }

            all_outputs.update(result.outputs)
            self._update_step_status(step_id, "completed")
            self._save_step_outputs(step_id, result.outputs)

            for artifact in result.artifacts:
                self._save_artifact(step_id, artifact)

        return {"status": "completed", "outputs": all_outputs}

    def _overlay_db_step_configs(self):
        """Merge per-step configs from DB rows (which include run-time overrides)
        on top of the template defaults."""
        if not self.db:
            return
        try:
            db_steps = self.db.get_steps(self.instance_id)
            for row in db_steps:
                sid = row["step_id"]
                if sid in self.steps and row.get("step_config_json"):
                    db_config = json.loads(row["step_config_json"])
                    self.steps[sid]["config"] = db_config
        except Exception as e:
            logger.warning(f"Could not overlay DB step configs: {e}")

    def _check_executors(self) -> list[str]:
        """Check that all step types in this workflow have registered executors.
        Returns list of missing step type names (empty = all good)."""
        from backend.workflows.step_types import STEP_REGISTRY
        missing = []
        for step_def in self.steps.values():
            st = step_def["type"]
            if st not in STEP_REGISTRY and st not in missing:
                missing.append(st)
        return missing

    def _topological_sort(self) -> list[str]:
        """Topological sort of the step graph via Kahn's algorithm."""
        in_degree = defaultdict(int)
        adjacency = defaultdict(list)
        all_step_ids = set(self.steps.keys())

        for edge in self.edges:
            src, dst = edge["from"], edge["to"]
            adjacency[src].append(dst)
            in_degree[dst] += 1

        for sid in all_step_ids:
            if sid not in in_degree:
                in_degree[sid] = 0

        queue = deque(sid for sid in all_step_ids if in_degree[sid] == 0)
        result = []
        while queue:
            node = queue.popleft()
            result.append(node)
            for neighbor in adjacency[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(result) != len(all_step_ids):
            raise ValueError("Workflow template contains a cycle")

        return result

    def _parallel_levels(self) -> list[list[str]]:
        """Group steps into execution levels. Steps in the same level share no
        dependency on each other and can run concurrently."""
        in_degree = defaultdict(int)
        adjacency = defaultdict(list)
        all_step_ids = set(self.steps.keys())

        for edge in self.edges:
            src, dst = edge["from"], edge["to"]
            adjacency[src].append(dst)
            in_degree[dst] += 1

        for sid in all_step_ids:
            if sid not in in_degree:
                in_degree[sid] = 0

        levels: list[list[str]] = []
        queue = [sid for sid in all_step_ids if in_degree[sid] == 0]

        while queue:
            levels.append(sorted(queue))
            next_queue = []
            for node in queue:
                for neighbor in adjacency[node]:
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        next_queue.append(neighbor)
            queue = next_queue

        return levels

    @staticmethod
    def _merge_outputs(target: dict, source: dict):
        """Merge source outputs into target, concatenating lists for shared keys."""
        for key, value in source.items():
            if key in target and isinstance(target[key], list) and isinstance(value, list):
                target[key] = target[key] + value
            else:
                target[key] = value

    def _get_upstream(self, step_id: str) -> list[str]:
        return [e["from"] for e in self.edges if e["to"] == step_id]

    def _update_step_status(self, step_id: str, status: str, error: Optional[str] = None):
        if self.db:
            try:
                self.db.update_step_status(self.instance_id, step_id, status, error)
            except Exception as e:
                logger.warning(f"Failed to update step status in DB: {e}")

    def _save_artifact(self, step_id: str, artifact: dict):
        if self.db:
            try:
                self.db.save_artifact(self.instance_id, step_id, artifact)
            except Exception as e:
                logger.warning(f"Failed to save artifact: {e}")

    def _save_step_outputs(self, step_id: str, outputs: dict):
        if self.db and outputs:
            try:
                self.db.save_step_outputs(self.instance_id, step_id, outputs)
            except Exception as e:
                logger.warning(f"Failed to save step outputs: {e}")

    def _save_gate_payload(self, step_id: str, payload: Optional[dict]):
        if self.db and payload:
            try:
                self.db.save_gate_payload(self.instance_id, step_id, payload)
            except Exception as e:
                logger.warning(f"Failed to save gate payload: {e}")


def validate_template(template: dict) -> list[str]:
    """Validate a workflow template structure. Returns list of errors (empty = valid)."""
    errors = []
    steps = template.get("steps")
    edges = template.get("edges")

    if not steps:
        errors.append("Template must have at least one step")
        return errors

    step_ids = {s["id"] for s in steps}

    for step in steps:
        if "id" not in step:
            errors.append("Every step must have an 'id'")
        if "type" not in step:
            errors.append(f"Step '{step.get('id', '?')}' missing 'type'")

    if edges:
        for edge in edges:
            if edge.get("from") not in step_ids:
                errors.append(f"Edge references unknown source step '{edge.get('from')}'")
            if edge.get("to") not in step_ids:
                errors.append(f"Edge references unknown target step '{edge.get('to')}'")

    connected = set()
    for edge in (edges or []):
        connected.add(edge["from"])
        connected.add(edge["to"])
    orphans = step_ids - connected
    if len(steps) > 1 and orphans:
        for orphan in orphans:
            errors.append(f"Step '{orphan}' is not connected to any other step")

    return errors
