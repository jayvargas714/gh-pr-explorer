#!/usr/bin/env python3
"""Pre-seed the workflow cache with unfiltered workflow runs.

Usage:
    python seed_workflow_cache.py owner/repo1 owner/repo2 ...
    python seed_workflow_cache.py --refresh   # re-seed all repos already in cache
"""

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

# Import helpers from the app module (no Flask dependency needed for these)
sys.path.insert(0, str(Path(__file__).parent))
from database import get_workflow_cache_db

# Load config
config_path = Path(__file__).parent / "config.json"
with open(config_path) as f:
    config = json.load(f)


def run_gh_command(args, check=True):
    """Run a gh CLI command and return the output."""
    try:
        result = subprocess.run(
            ["gh"] + args,
            capture_output=True,
            text=True,
            check=check,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"gh command failed: {e.stderr}")
    except FileNotFoundError:
        raise RuntimeError("gh CLI not found. Please install GitHub CLI.")


def parse_json_output(output):
    """Parse JSON output from gh CLI."""
    if not output:
        return None
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return None


def fetch_workflow_data(owner, repo):
    """Fetch unfiltered workflow runs in parallel batches."""
    max_runs = config.get("workflow_cache_max_runs", 1000)
    max_pages = max_runs // 100

    base_url = f"repos/{owner}/{repo}/actions/runs?per_page=100"
    jq_query = (
        "[.workflow_runs[] | {"
        "id, name, display_title, status, conclusion, "
        "created_at, updated_at, event, head_branch, "
        "run_attempt, run_number, html_url, "
        "actor_login: .actor.login, "
        "workflow_id: .workflow_id"
        "}]"
    )

    def fetch_page(page_num):
        try:
            output = run_gh_command(["api", f"{base_url}&page={page_num}", "--jq", jq_query])
            return parse_json_output(output) or []
        except RuntimeError:
            return []

    def fetch_workflows():
        try:
            wf_output = run_gh_command([
                "api", f"repos/{owner}/{repo}/actions/workflows",
                "--jq", "[.workflows[] | {id, name, state, path}]"
            ])
            return parse_json_output(wf_output) or []
        except RuntimeError:
            return []

    def fetch_total_count():
        try:
            count_output = run_gh_command([
                "api", f"repos/{owner}/{repo}/actions/runs?per_page=1&page=1",
                "--jq", ".total_count"
            ])
            return int(count_output.strip()) if count_output.strip() else 0
        except (RuntimeError, ValueError):
            return 0

    runs = []
    workflows = []
    all_time_total = 0

    # Batch 1: workflows + total count + pages 1-3
    batch1_pages = min(3, max_pages)
    with ThreadPoolExecutor(max_workers=5) as executor:
        wf_future = executor.submit(fetch_workflows)
        count_future = executor.submit(fetch_total_count)
        page_futures = {executor.submit(fetch_page, p): p for p in range(1, batch1_pages + 1)}

        workflows = wf_future.result()
        all_time_total = count_future.result()

        page_results = {}
        for future in page_futures:
            page_num = page_futures[future]
            page_results[page_num] = future.result()

    needs_more = True
    for p in range(1, batch1_pages + 1):
        page_runs = page_results.get(p, [])
        runs.extend(page_runs)
        if len(page_runs) < 100:
            needs_more = False
            break

    # Batch 2: pages 4-8
    if needs_more and max_pages > 3:
        batch2_end = min(8, max_pages)
        with ThreadPoolExecutor(max_workers=5) as executor:
            page_futures = {executor.submit(fetch_page, p): p for p in range(4, batch2_end + 1)}
            page_results = {}
            for future in page_futures:
                page_num = page_futures[future]
                page_results[page_num] = future.result()

        for p in range(4, batch2_end + 1):
            page_runs = page_results.get(p, [])
            runs.extend(page_runs)
            if len(page_runs) < 100:
                needs_more = False
                break

    # Batch 3: pages 9-10
    if needs_more and max_pages > 8:
        batch3_end = min(10, max_pages)
        with ThreadPoolExecutor(max_workers=5) as executor:
            page_futures = {executor.submit(fetch_page, p): p for p in range(9, batch3_end + 1)}
            page_results = {}
            for future in page_futures:
                page_num = page_futures[future]
                page_results[page_num] = future.result()

        for p in range(9, batch3_end + 1):
            page_runs = page_results.get(p, [])
            runs.extend(page_runs)
            if len(page_runs) < 100:
                break

    # Pre-compute duration_seconds
    for run in runs:
        created = run.get("created_at")
        updated = run.get("updated_at")
        if created and updated:
            try:
                c = datetime.fromisoformat(created.replace("Z", "+00:00"))
                u = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                run["duration_seconds"] = max(int((u - c).total_seconds()), 0)
            except (ValueError, TypeError):
                run["duration_seconds"] = None
        else:
            run["duration_seconds"] = None

    return {"runs": runs, "workflows": workflows, "all_time_total": all_time_total}


def main():
    parser = argparse.ArgumentParser(description="Pre-seed the workflow cache")
    parser.add_argument("repos", nargs="*", help="Repositories to seed (owner/repo format)")
    parser.add_argument("--refresh", action="store_true",
                        help="Re-seed all repos already in the cache")
    args = parser.parse_args()

    db = get_workflow_cache_db()

    repos = list(args.repos)
    if args.refresh:
        cached_repos = db.get_all_repos()
        repos.extend(r for r in cached_repos if r not in repos)

    if not repos:
        print("No repos specified. Usage:")
        print("  python seed_workflow_cache.py owner/repo1 owner/repo2 ...")
        print("  python seed_workflow_cache.py --refresh")
        sys.exit(1)

    for repo_key in repos:
        parts = repo_key.split("/", 1)
        if len(parts) != 2:
            print(f"Skipping invalid repo format: {repo_key} (expected owner/repo)")
            continue

        owner, repo = parts
        print(f"Seeding {repo_key}...", end=" ", flush=True)
        start = time.time()
        try:
            data = fetch_workflow_data(owner, repo)
            db.save_cache(repo_key, data)
            elapsed = time.time() - start
            print(f"fetched {len(data['runs'])} runs ({elapsed:.1f}s)")
        except Exception as e:
            elapsed = time.time() - start
            print(f"FAILED ({elapsed:.1f}s): {e}")


if __name__ == "__main__":
    main()
