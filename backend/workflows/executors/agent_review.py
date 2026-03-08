from __future__ import annotations
"""Agent Review step — dispatches prompts to AI agents with per-domain tracking.

Each domain's agent is started as a subprocess immediately (no thread pool
serialization). The executor polls all agents in a single loop and supports
cancel / rerun of individual domains from the UI.
"""

import logging
import threading
import time

from backend.agents import get_agent, AgentStatus
from backend.workflows.executor import StepExecutor, StepResult
from backend.workflows.step_types import register_step

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 5

_live_output_store: dict[str, str] = {}
_live_output_lock = threading.Lock()

_agent_domain_store: dict[str, dict[str, dict]] = {}
_agent_domain_lock = threading.Lock()
_rerun_queue: dict[str, dict[str, dict]] = {}


def get_agent_live_output(instance_id: int, step_id: str) -> str:
    key = f"{instance_id}:{step_id}"
    with _live_output_lock:
        return _live_output_store.get(key, "")


def get_agent_domains(instance_id: int, step_id: str) -> dict[str, dict]:
    """Return serialisable per-domain status (no internal refs)."""
    key = f"{instance_id}:{step_id}"
    with _agent_domain_lock:
        raw = _agent_domain_store.get(key, {})
        return {
            d: {
                "status": info.get("status", "unknown"),
                "agent_name": info.get("agent_name", ""),
                "started_at": info.get("started_at"),
                "completed_at": info.get("completed_at"),
                "pid": info.get("pid"),
                "error": info.get("error"),
            }
            for d, info in raw.items()
        }


def cancel_agent_domain(instance_id: int, step_id: str, domain: str) -> bool:
    key = f"{instance_id}:{step_id}"
    with _agent_domain_lock:
        info = _agent_domain_store.get(key, {}).get(domain)
    if not info or info.get("status") != "running":
        return False
    agent_ref = info.get("agent_ref")
    handle_ref = info.get("handle_ref")
    if agent_ref and handle_ref:
        agent_ref.cancel(handle_ref)
    with _agent_domain_lock:
        if key in _agent_domain_store and domain in _agent_domain_store[key]:
            _agent_domain_store[key][domain]["status"] = "cancelled"
            _agent_domain_store[key][domain]["completed_at"] = time.time()
    return True


def rerun_agent_domain(instance_id: int, step_id: str, domain: str) -> bool:
    """Queue a cancelled/failed domain for re-execution within the running step."""
    key = f"{instance_id}:{step_id}"
    with _agent_domain_lock:
        info = _agent_domain_store.get(key, {}).get(domain)
        if not info or info.get("status") == "running":
            return False
        prompt_data = info.get("prompt_data")
        if not prompt_data:
            return False
        if key not in _rerun_queue:
            _rerun_queue[key] = {}
        _rerun_queue[key][domain] = prompt_data
        _agent_domain_store[key][domain]["status"] = "rerunning"
    return True


def _set_live_output(instance_id: int, step_id: str, text: str):
    key = f"{instance_id}:{step_id}"
    with _live_output_lock:
        _live_output_store[key] = text


def _clear_live_output(instance_id: int, step_id: str):
    key = f"{instance_id}:{step_id}"
    with _live_output_lock:
        _live_output_store.pop(key, None)


def _register_domain(
    key: str, domain: str, agent_ref, handle_ref,
    prompt_data: dict, agent_name: str,
    status: str = "running", error: str | None = None,
):
    with _agent_domain_lock:
        if key not in _agent_domain_store:
            _agent_domain_store[key] = {}
        info: dict = {
            "status": status,
            "agent_ref": agent_ref,
            "handle_ref": handle_ref,
            "prompt_data": prompt_data,
            "agent_name": agent_name,
            "started_at": time.time(),
            "pid": handle_ref.metadata.get("pid") if handle_ref else None,
        }
        if error:
            info["error"] = error
            info["result"] = {
                "status": "failed", "pr_number": prompt_data.get("pr_number"),
                "error": error, "agent_name": agent_name,
            }
            info["completed_at"] = time.time()
        _agent_domain_store[key][domain] = info


@register_step("agent_review")
class AgentReviewExecutor(StepExecutor):

    def execute(self, inputs: dict) -> StepResult:
        agent_name = self.step_config.get("agent", "claude")
        phase = self.step_config.get("phase", "a")
        prompts = inputs.get("prompts", [])
        inst_id = self.instance_config.get("_instance_id", 0)
        step_id = self.step_config.get("_step_id", "")

        if not prompts:
            return StepResult(success=False, error="No prompts provided to agent_review step")

        if phase == "b":
            isolation = (
                "IMPORTANT: You are producing a completely independent review (Review B). "
                "Do NOT reference or consider any prior AI-generated reviews of this PR. "
                "Your value is finding things the other reviewer missed, so be thorough "
                "and approach the code from a fresh perspective.\n\n"
            )
            prompts = [{**p, "prompt": isolation + p.get("prompt", "")} for p in prompts]

        try:
            agent = get_agent(agent_name)
        except Exception as e:
            return StepResult(success=False, error=f"Failed to get agent '{agent_name}': {e}")

        key = f"{inst_id}:{step_id}"

        for p in prompts:
            domain = p.get("domain", f"pr-{p.get('pr_number')}")
            context = self._build_context(p, phase, inst_id)
            try:
                handle = agent.start_review(p.get("prompt", ""), context)
                _register_domain(key, domain, agent, handle, p, agent_name)
            except Exception as e:
                logger.error(f"Failed to start review for domain {domain}: {e}")
                _register_domain(key, domain, None, None, p, agent_name,
                                 status="failed", error=str(e))

        from backend.workflows.cancellation import is_cancelled, AGENT_POLL_TIMEOUT

        results: dict[str, dict] = {}
        elapsed = 0
        while True:
            if inst_id and is_cancelled(inst_id):
                with _agent_domain_lock:
                    snapshot = dict(_agent_domain_store.get(key, {}))
                for domain, info in snapshot.items():
                    if domain in results:
                        continue
                    agent_ref = info.get("agent_ref")
                    handle_ref = info.get("handle_ref")
                    if agent_ref and handle_ref and info.get("status") == "running":
                        agent_ref.cancel(handle_ref)
                break

            self._process_reruns(key, agent, phase, inst_id, agent_name, results)

            all_done = True
            with _agent_domain_lock:
                snapshot = dict(_agent_domain_store.get(key, {}))

            for domain, info in snapshot.items():
                if domain in results:
                    continue
                st = info.get("status", "")
                if st in ("completed", "failed", "cancelled"):
                    if domain not in results:
                        results[domain] = info.get("result", {
                            "status": st,
                            "pr_number": info.get("prompt_data", {}).get("pr_number"),
                            "agent_name": agent_name,
                        })
                    continue
                if st != "running":
                    all_done = False
                    continue

                all_done = False
                agent_ref = info.get("agent_ref")
                handle_ref = info.get("handle_ref")
                if not agent_ref or not handle_ref:
                    continue

                status = agent_ref.check_status(handle_ref)
                if status == AgentStatus.RUNNING:
                    live = agent_ref.get_live_output(handle_ref)
                    with _agent_domain_lock:
                        if key in _agent_domain_store and domain in _agent_domain_store[key]:
                            _agent_domain_store[key][domain]["live_output"] = live
                elif status == AgentStatus.COMPLETED:
                    self._collect_completed(key, domain, info, agent_ref, handle_ref,
                                            agent_name, phase, results)
                else:
                    self._collect_failed(key, domain, info, agent_ref, handle_ref,
                                         agent_name, results)

            if all_done:
                break

            if elapsed >= AGENT_POLL_TIMEOUT:
                logger.error(f"Agent review timed out after {elapsed}s, cancelling remaining")
                with _agent_domain_lock:
                    snapshot = dict(_agent_domain_store.get(key, {}))
                for domain, info in snapshot.items():
                    if domain in results:
                        continue
                    agent_ref = info.get("agent_ref")
                    handle_ref = info.get("handle_ref")
                    if agent_ref and handle_ref and info.get("status") == "running":
                        agent_ref.cancel(handle_ref)
                break

            self._update_composite(inst_id, step_id, key)
            time.sleep(_POLL_INTERVAL)
            elapsed += _POLL_INTERVAL

        _clear_live_output(inst_id, step_id)
        with _agent_domain_lock:
            _agent_domain_store.pop(key, None)
            _rerun_queue.pop(key, None)

        reviews = list(results.values())
        completed_reviews = [r for r in reviews if r.get("status") == "completed"]
        failed_reviews = [r for r in reviews if r.get("status") in ("failed", "cancelled")]

        if not completed_reviews and failed_reviews:
            errors = "; ".join(
                f'PR #{r.get("pr_number", "?")}: {r.get("error", "unknown")}'
                for r in failed_reviews
            )
            return StepResult(
                success=False,
                error=f"All reviews failed ({agent_name}): {errors}",
                outputs={"reviews": reviews, "agent_name": agent_name},
            )

        return StepResult(
            success=True,
            outputs={"reviews": reviews, "agent_name": agent_name},
            artifacts=[
                {"type": "review", "pr_number": r["pr_number"], "data": r}
                for r in completed_reviews
            ],
        )

    @staticmethod
    def _build_context(prompt_data: dict, phase: str, inst_id: int) -> dict:
        return {
            "pr_url": prompt_data.get("pr_url", ""),
            "pr_number": prompt_data.get("pr_number"),
            "pr_title": prompt_data.get("pr_title", ""),
            "pr_author": prompt_data.get("pr_author", ""),
            "owner": prompt_data.get("owner", ""),
            "repo": prompt_data.get("repo", ""),
            "phase": phase,
            "domain": prompt_data.get("domain", ""),
            "instance_id": inst_id,
        }

    @staticmethod
    def _process_reruns(key, agent, phase, inst_id, agent_name, results):
        with _agent_domain_lock:
            reruns = _rerun_queue.pop(key, {})
        for domain, prompt_data in reruns.items():
            context = AgentReviewExecutor._build_context(prompt_data, phase, inst_id)
            try:
                handle = agent.start_review(prompt_data.get("prompt", ""), context)
                _register_domain(key, domain, agent, handle, prompt_data, agent_name)
                results.pop(domain, None)
            except Exception as e:
                logger.error(f"Rerun failed for domain {domain}: {e}")
                _register_domain(key, domain, None, None, prompt_data, agent_name,
                                 status="failed", error=str(e))

    @staticmethod
    def _collect_completed(key, domain, info, agent_ref, handle_ref,
                           agent_name, phase, results):
        artifact = agent_ref.get_output(handle_ref)
        if hasattr(agent_ref, "cleanup"):
            agent_ref.cleanup(handle_ref)
        entry = {
            "pr_number": info["prompt_data"].get("pr_number"),
            "status": "completed",
            "agent_name": agent_name,
            "phase": phase,
            "content_md": artifact.content_md,
            "content_json": artifact.content_json,
            "file_path": artifact.file_path,
            "score": artifact.score,
            "head_sha": info["prompt_data"].get("head_sha", ""),
        }
        d = info["prompt_data"].get("domain")
        if d:
            entry["domain"] = d
        results[domain] = entry
        with _agent_domain_lock:
            if key in _agent_domain_store and domain in _agent_domain_store[key]:
                _agent_domain_store[key][domain]["status"] = "completed"
                _agent_domain_store[key][domain]["result"] = entry
                _agent_domain_store[key][domain]["completed_at"] = time.time()

    @staticmethod
    def _collect_failed(key, domain, info, agent_ref, handle_ref,
                        agent_name, results):
        artifact = agent_ref.get_output(handle_ref)
        if hasattr(agent_ref, "cleanup"):
            agent_ref.cleanup(handle_ref)
        entry = {
            "pr_number": info["prompt_data"].get("pr_number"),
            "status": "failed",
            "agent_name": agent_name,
            "error": artifact.error,
        }
        results[domain] = entry
        with _agent_domain_lock:
            if key in _agent_domain_store and domain in _agent_domain_store[key]:
                _agent_domain_store[key][domain]["status"] = "failed"
                _agent_domain_store[key][domain]["result"] = entry
                _agent_domain_store[key][domain]["completed_at"] = time.time()

    @staticmethod
    def _update_composite(inst_id, step_id, key):
        parts = []
        with _agent_domain_lock:
            domains = _agent_domain_store.get(key, {})
            for d, info in domains.items():
                st = info.get("status", "")
                live = info.get("live_output", "")
                if st == "running" and live:
                    parts.append(f"--- [{d}] ---\n{live}")
                elif st == "running":
                    parts.append(f"--- [{d}] ---\nStarting...")
                elif st == "completed":
                    parts.append(f"--- [{d}] ---\n[Completed]")
                elif st == "failed":
                    err = info.get("error", "unknown")
                    parts.append(f"--- [{d}] ---\n[Failed: {err}]")
                elif st == "cancelled":
                    parts.append(f"--- [{d}] ---\n[Cancelled]")
                elif st == "rerunning":
                    parts.append(f"--- [{d}] ---\n[Restarting...]")
        if parts:
            _set_live_output(inst_id, step_id, "\n\n".join(parts))
