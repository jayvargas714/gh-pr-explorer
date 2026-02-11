"""Apply filters to cached workflow runs, compute aggregate stats."""


def filter_and_compute_stats(cached_data, filters):
    """Apply filters to cached workflow data and compute aggregate stats.

    Args:
        cached_data: dict with keys: runs, workflows, all_time_total
        filters: dict with optional keys: workflow_id, branch, event, conclusion, status
    Returns:
        dict with keys: runs, stats, workflows
    """
    runs = cached_data.get("runs", [])
    workflows = cached_data.get("workflows", [])
    all_time_total = cached_data.get("all_time_total", 0)

    filtered = runs
    wf_id = filters.get("workflow_id")
    if wf_id:
        try:
            wf_id_int = int(wf_id)
            filtered = [r for r in filtered if r.get("workflow_id") == wf_id_int]
        except (ValueError, TypeError):
            pass

    branch = filters.get("branch")
    if branch:
        filtered = [r for r in filtered if r.get("head_branch") == branch]

    event = filters.get("event")
    if event:
        filtered = [r for r in filtered if r.get("event") == event]

    conclusion = filters.get("conclusion")
    status_filter = filters.get("status")
    if conclusion:
        filtered = [r for r in filtered if r.get("conclusion") == conclusion]
    elif status_filter:
        filtered = [r for r in filtered
                    if r.get("status") == status_filter or r.get("conclusion") == status_filter]

    total_runs = len(filtered)
    success_count = 0
    failure_count = 0
    total_duration = 0
    duration_count = 0
    runs_by_workflow = {}

    for run in filtered:
        c = run.get("conclusion")
        if c == "success":
            success_count += 1
        elif c == "failure":
            failure_count += 1

        dur = run.get("duration_seconds")
        if dur is not None and c in ("success", "failure"):
            total_duration += dur
            duration_count += 1

        wf_name = run.get("name", "Unknown")
        if wf_name not in runs_by_workflow:
            runs_by_workflow[wf_name] = {"total": 0, "failures": 0}
        runs_by_workflow[wf_name]["total"] += 1
        if c == "failure":
            runs_by_workflow[wf_name]["failures"] += 1

    completed_runs = success_count + failure_count
    stats = {
        "total_runs": total_runs,
        "all_time_total": all_time_total,
        "pass_rate": round((success_count / completed_runs * 100), 1) if completed_runs > 0 else 0,
        "avg_duration": round(total_duration / duration_count) if duration_count > 0 else 0,
        "failure_count": failure_count,
        "success_count": success_count,
        "runs_by_workflow": runs_by_workflow
    }

    return {"runs": filtered, "stats": stats, "workflows": workflows}
