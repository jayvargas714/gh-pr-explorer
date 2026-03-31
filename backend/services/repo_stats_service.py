"""Repository statistics service: parallel GitHub API fetching and LOC calculation."""

import json
import logging
import os
import shutil
import subprocess
import tempfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from backend.services.github_service import run_gh_command, parse_json_output, fetch_github_stats_api

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXTENSION_TO_LANGUAGE = {
    ".py": "Python",
    ".pyw": "Python",
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".go": "Go",
    ".rs": "Rust",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".cxx": "C++",
    ".cc": "C++",
    ".hpp": "C++",
    ".hxx": "C++",
    ".cs": "C#",
    ".rb": "Ruby",
    ".rake": "Ruby",
    ".php": "PHP",
    ".swift": "Swift",
    ".scala": "Scala",
    ".sbt": "Scala",
    ".r": "R",
    ".R": "R",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".fish": "Shell",
    ".ps1": "PowerShell",
    ".psm1": "PowerShell",
    ".html": "HTML",
    ".htm": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
    ".sass": "SASS",
    ".less": "LESS",
    ".sql": "SQL",
    ".lua": "Lua",
    ".ex": "Elixir",
    ".exs": "Elixir",
    ".erl": "Erlang",
    ".hrl": "Erlang",
    ".hs": "Haskell",
    ".lhs": "Haskell",
    ".ml": "OCaml",
    ".mli": "OCaml",
    ".clj": "Clojure",
    ".cljs": "Clojure",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".tf": "Terraform",
    ".tfvars": "Terraform",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".json": "JSON",
    ".toml": "TOML",
    ".xml": "XML",
    ".md": "Markdown",
    ".mdx": "Markdown",
    ".rst": "reStructuredText",
    ".dart": "Dart",
    ".m": "Objective-C",
    ".mm": "Objective-C",
}

LINE_COMMENT_MARKERS = {
    "Python": "#",
    "Ruby": "#",
    "Shell": "#",
    "PowerShell": "#",
    "R": "#",
    "YAML": "#",
    "TOML": "#",
    "Elixir": "#",
    "JavaScript": "//",
    "TypeScript": "//",
    "Java": "//",
    "Kotlin": "//",
    "Go": "//",
    "Rust": "//",
    "C": "//",
    "C++": "//",
    "C#": "//",
    "Swift": "//",
    "Scala": "//",
    "Dart": "//",
    "PHP": "//",
    "SQL": "--",
    "Lua": "--",
    "Haskell": "--",
    "OCaml": "--",
}

BLOCK_COMMENT_PAIRS = {
    "C": ("/*", "*/"),
    "C++": ("/*", "*/"),
    "C#": ("/*", "*/"),
    "Java": ("/*", "*/"),
    "JavaScript": ("/*", "*/"),
    "TypeScript": ("/*", "*/"),
    "Go": ("/*", "*/"),
    "Rust": ("/*", "*/"),
    "Swift": ("/*", "*/"),
    "Kotlin": ("/*", "*/"),
    "Scala": ("/*", "*/"),
    "Dart": ("/*", "*/"),
    "PHP": ("/*", "*/"),
    "CSS": ("/*", "*/"),
    "SCSS": ("/*", "*/"),
    "SASS": ("/*", "*/"),
    "LESS": ("/*", "*/"),
    "HTML": ("<!--", "-->"),
    "XML": ("<!--", "-->"),
    "Vue": ("<!--", "-->"),
    "OCaml": ("(*", "*)"),
}

SKIP_DIRS = {
    ".git", "node_modules", "vendor", "__pycache__", "venv", ".venv",
    "dist", "build", "target", ".tox", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", "coverage", ".coverage", ".nyc_output", "out",
    ".next", ".nuxt", ".svelte-kit", "eggs", ".eggs", "htmlcov",
    "site-packages", ".idea", ".vscode", ".DS_Store",
}

BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".tiff", ".webp",
    ".svg", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".a", ".lib",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".mp3", ".mp4", ".avi", ".mov", ".wav", ".flac",
    ".pyc", ".pyo", ".class", ".o", ".obj",
    ".lock",  # lockfiles are text but not useful to count
    ".min.js", ".min.css",
    ".map",
    ".db", ".sqlite", ".sqlite3",
    ".bin", ".dat", ".parquet", ".pkl", ".npy", ".npz",
}


# ---------------------------------------------------------------------------
# fetch_repo_stats
# ---------------------------------------------------------------------------

def fetch_repo_stats(owner, repo):
    """Fetch all repository statistics in parallel using ThreadPoolExecutor.

    Returns a dict with keys: overview, languages, files_by_extension, code, prs.
    """
    full_repo = f"{owner}/{repo}"

    def _fetch_overview():
        try:
            output = run_gh_command(["api", f"repos/{full_repo}"])
            return parse_json_output(output)
        except RuntimeError as e:
            logger.warning(f"Failed to fetch overview for {full_repo}: {e}")
            return {}

    def _fetch_languages():
        try:
            output = run_gh_command(["api", f"repos/{full_repo}/languages"])
            result = parse_json_output(output)
            return result if isinstance(result, dict) else {}
        except RuntimeError as e:
            logger.warning(f"Failed to fetch languages for {full_repo}: {e}")
            return {}

    def _fetch_file_tree():
        try:
            result = subprocess.run(
                ["gh", "api", f"repos/{full_repo}/git/trees/HEAD",
                 "-q", ".tree[].path", "--paginate", "-X", "GET", "-f", "recursive=1"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.stdout:
                return [p for p in result.stdout.split("\n") if p.strip()]
            return []
        except Exception as e:
            logger.warning(f"Failed to fetch file tree for {full_repo}: {e}")
            return []

    def _fetch_pr_count(qualifier):
        try:
            q = f"repo:{full_repo}+is:pr+{qualifier.replace(' ', '+')}"
            output = run_gh_command([
                "api", f"search/issues?q={q}&per_page=1",
                "--jq", ".total_count",
            ])
            return int(output.strip()) if output.strip().isdigit() else 0
        except (RuntimeError, ValueError) as e:
            logger.warning(f"Failed to fetch PR count ({qualifier}) for {full_repo}: {e}")
            return 0

    def _fetch_branch_count():
        total = 0
        page = 1
        while True:
            try:
                output = run_gh_command([
                    "api", f"repos/{full_repo}/branches?per_page=100&page={page}",
                ])
                branches = parse_json_output(output)
                if not isinstance(branches, list):
                    break
                total += len(branches)
                if len(branches) < 100:
                    break
                page += 1
            except RuntimeError as e:
                logger.warning(f"Failed to fetch branches page {page} for {full_repo}: {e}")
                break
        return total

    def _fetch_contributors_stats():
        """Fetch stats/contributors and return (total_commits, contributor_count)."""
        contributors = fetch_github_stats_api(owner, repo, "stats/contributors")
        if not isinstance(contributors, list):
            return 0, 0
        total = sum(c.get("total", 0) for c in contributors if isinstance(c, dict))
        return total, len(contributors)

    with ThreadPoolExecutor(max_workers=7) as executor:
        f_overview = executor.submit(_fetch_overview)
        f_languages = executor.submit(_fetch_languages)
        f_tree = executor.submit(_fetch_file_tree)
        f_pr_open = executor.submit(_fetch_pr_count, "is:open")
        f_pr_closed = executor.submit(_fetch_pr_count, "is:closed is:unmerged")
        f_pr_merged = executor.submit(_fetch_pr_count, "is:merged")
        f_branches = executor.submit(_fetch_branch_count)
        f_contrib_stats = executor.submit(_fetch_contributors_stats)

        overview_raw = f_overview.result()
        languages_raw = f_languages.result()
        tree_paths = f_tree.result()
        pr_open = f_pr_open.result()
        pr_closed = f_pr_closed.result()
        pr_merged = f_pr_merged.result()
        branch_count = f_branches.result()
        total_commits, total_contributors = f_contrib_stats.result()

    # --- overview ---
    license_info = overview_raw.get("license") or {}
    created_at_str = overview_raw.get("created_at")
    age_days = None
    if created_at_str:
        try:
            created_dt = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - created_dt).days
        except (ValueError, TypeError):
            pass

    overview = {
        "name": overview_raw.get("name"),
        "full_name": overview_raw.get("full_name"),
        "description": overview_raw.get("description"),
        "default_branch": overview_raw.get("default_branch"),
        "license": license_info.get("spdx_id") if license_info else None,
        "created_at": created_at_str,
        "age_days": age_days,
        "size_kb": overview_raw.get("size"),
        "stars": overview_raw.get("stargazers_count", 0),
        "forks": overview_raw.get("forks_count", 0),
        "watchers": overview_raw.get("subscribers_count", 0),
        "open_issues": overview_raw.get("open_issues_count", 0),
    }

    # --- languages ---
    total_bytes = sum(languages_raw.values()) if languages_raw else 0
    languages = []
    for lang, byte_count in sorted(languages_raw.items(), key=lambda x: x[1], reverse=True):
        pct = round(byte_count / total_bytes * 100, 1) if total_bytes > 0 else 0.0
        languages.append({"name": lang, "bytes": byte_count, "percentage": pct})

    # --- files by extension (filter out vendored/generated directories) ---
    ext_counter = Counter()
    filtered_paths = [
        p for p in tree_paths
        if not any(skip in p.split("/") for skip in SKIP_DIRS)
    ]
    total_files = len(filtered_paths)
    for path in filtered_paths:
        _, ext = os.path.splitext(path)
        ext = ext.lower() if ext else "(none)"
        ext_counter[ext] += 1

    files_by_extension = []
    for ext, count in ext_counter.most_common():
        pct = round(count / total_files * 100, 1) if total_files > 0 else 0.0
        files_by_extension.append({"extension": ext, "count": count, "percentage": pct})

    # --- code summary ---
    code = {
        "total_commits": total_commits,
        "total_files": total_files,
        "total_contributors": total_contributors,
        "total_branches": branch_count,
    }

    # --- PR counts ---
    prs = {
        "open": pr_open,
        "closed": pr_closed,
        "merged": pr_merged,
        "total_all_time": pr_open + pr_closed + pr_merged,
    }

    return {
        "overview": overview,
        "languages": languages,
        "files_by_extension": files_by_extension,
        "code": code,
        "prs": prs,
    }


# ---------------------------------------------------------------------------
# calculate_loc
# ---------------------------------------------------------------------------

def calculate_loc(owner, repo):
    """Shallow-clone the repo and count lines per language.

    Returns a dict with:
      - loc: list of {language, files, blank, comment, code}
      - totals: {files, blank, comment, code}
    """
    full_repo = f"{owner}/{repo}"
    tmpdir = tempfile.mkdtemp(prefix="gh_pr_explorer_loc_")

    try:
        # Use gh repo clone for authenticated access (handles private repos)
        subprocess.run(
            ["gh", "repo", "clone", full_repo, tmpdir, "--", "--depth", "1", "--quiet"],
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        logger.error(f"Git clone timed out for {full_repo}")
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise RuntimeError(f"Clone timed out for {full_repo}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Git clone failed for {full_repo}: {e.stderr}")
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise RuntimeError(f"Clone failed for {full_repo}: {e.stderr}")

    # Accumulate stats per language
    lang_stats = defaultdict(lambda: {"files": 0, "blank": 0, "comment": 0, "code": 0})

    try:
        for dirpath, dirnames, filenames in os.walk(tmpdir):
            # Prune skipped directories in-place so os.walk doesn't recurse into them
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

            for filename in filenames:
                filepath = os.path.join(dirpath, filename)
                _, ext = os.path.splitext(filename)
                ext_lower = ext.lower()

                # Skip binary extensions
                if ext_lower in BINARY_EXTENSIONS:
                    continue

                language = EXTENSION_TO_LANGUAGE.get(ext) or EXTENSION_TO_LANGUAGE.get(ext_lower)
                if language is None:
                    continue

                # Try to read as text
                try:
                    with open(filepath, "r", encoding="utf-8", errors="ignore") as fh:
                        raw_lines = fh.readlines()
                except OSError:
                    continue

                line_marker = LINE_COMMENT_MARKERS.get(language)
                block_pair = BLOCK_COMMENT_PAIRS.get(language)
                block_start = block_pair[0] if block_pair else None
                block_end = block_pair[1] if block_pair else None

                blank = 0
                comment = 0
                code = 0
                in_block = False

                for raw_line in raw_lines:
                    stripped = raw_line.strip()

                    if not stripped:
                        blank += 1
                        continue

                    # Handle block comment state
                    if in_block:
                        comment += 1
                        if block_end and block_end in stripped:
                            in_block = False
                        continue

                    # Detect start of block comment
                    if block_start and stripped.startswith(block_start):
                        comment += 1
                        # Check if it ends on the same line
                        remainder = stripped[len(block_start):]
                        if not (block_end and block_end in remainder):
                            in_block = True
                        continue

                    # Detect line comment
                    if line_marker and stripped.startswith(line_marker):
                        comment += 1
                        continue

                    code += 1

                lang_stats[language]["files"] += 1
                lang_stats[language]["blank"] += blank
                lang_stats[language]["comment"] += comment
                lang_stats[language]["code"] += code

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    # Sort by code lines descending
    loc = []
    totals = {"files": 0, "blank": 0, "comment": 0, "code": 0}
    for language, stats in sorted(lang_stats.items(), key=lambda x: x[1]["code"], reverse=True):
        entry = {"language": language, **stats}
        loc.append(entry)
        totals["files"] += stats["files"]
        totals["blank"] += stats["blank"]
        totals["comment"] += stats["comment"]
        totals["code"] += stats["code"]

    return {"loc": loc, "totals": totals}
