"""Review JSON schema: validation, JSON<->markdown conversion, section name config."""

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from backend.config import get_config

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0.0"

# Load the JSON Schema spec from the companion file
_SCHEMA_PATH = Path(__file__).parent / "review_schema_spec.json"
with open(_SCHEMA_PATH) as _f:
    REVIEW_JSON_SCHEMA = json.load(_f)

# Default section display names (can be overridden in config.json)
DEFAULT_SECTION_NAMES = {
    "critical": "Critical Issues",
    "major": "Major Concerns",
    "minor": "Minor Issues",
}


def get_section_display_names() -> Dict[str, str]:
    """Read section display names from config, falling back to defaults."""
    config = get_config()
    overrides = config.get("review_section_names", {})
    names = dict(DEFAULT_SECTION_NAMES)
    names.update(overrides)
    return names


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_review_json(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validate a review dict against the schema.

    Returns (is_valid, list_of_error_messages).
    Uses lightweight hand-rolled checks so we don't require jsonschema lib.
    """
    errors: List[str] = []

    if not isinstance(data, dict):
        return False, ["Root must be a JSON object"]

    # Required top-level keys
    for key in ("schema_version", "metadata", "summary", "sections", "score"):
        if key not in data:
            errors.append(f"Missing required key: {key}")

    # schema_version
    sv = data.get("schema_version")
    if sv and sv != SCHEMA_VERSION:
        errors.append(f"Unknown schema_version: {sv} (expected {SCHEMA_VERSION})")

    # metadata
    meta = data.get("metadata")
    if isinstance(meta, dict):
        if "pr_number" not in meta:
            errors.append("metadata.pr_number is required")
        if "repository" not in meta:
            errors.append("metadata.repository is required")
    elif meta is not None:
        errors.append("metadata must be an object")

    # sections
    sections = data.get("sections")
    if isinstance(sections, list):
        valid_types = {"critical", "major", "minor"}
        for i, sec in enumerate(sections):
            if not isinstance(sec, dict):
                errors.append(f"sections[{i}] must be an object")
                continue
            sec_type = sec.get("type")
            if sec_type not in valid_types:
                errors.append(f"sections[{i}].type must be one of {valid_types}, got {sec_type!r}")
            if "display_name" not in sec:
                errors.append(f"sections[{i}].display_name is required")
            issues = sec.get("issues")
            if not isinstance(issues, list):
                errors.append(f"sections[{i}].issues must be an array")
            else:
                for j, issue in enumerate(issues):
                    if not isinstance(issue, dict):
                        errors.append(f"sections[{i}].issues[{j}] must be an object")
                        continue
                    if "title" not in issue:
                        errors.append(f"sections[{i}].issues[{j}].title is required")
                    if "problem" not in issue:
                        errors.append(f"sections[{i}].issues[{j}].problem is required")
                    loc = issue.get("location")
                    if not isinstance(loc, dict) or "file" not in loc:
                        errors.append(f"sections[{i}].issues[{j}].location.file is required")
    elif sections is not None:
        errors.append("sections must be an array")

    # score
    score = data.get("score")
    if isinstance(score, dict):
        overall = score.get("overall")
        if overall is None:
            errors.append("score.overall is required")
        elif not isinstance(overall, (int, float)):
            errors.append("score.overall must be a number")
        elif not (0 <= overall <= 10):
            errors.append("score.overall must be between 0 and 10")
    elif score is not None:
        errors.append("score must be an object")

    return len(errors) == 0, errors


# ---------------------------------------------------------------------------
# JSON -> Markdown
# ---------------------------------------------------------------------------

def json_to_markdown(review: Dict[str, Any]) -> str:
    """Convert a structured review JSON dict to clean markdown.

    Produces markdown matching the existing review file format so
    ReviewViewer, GitHub posts, and .md file output all work as before.
    """
    lines: List[str] = []
    meta = review.get("metadata", {})

    # Title
    pr_num = meta.get("pr_number", "?")
    pr_title = meta.get("pr_title", "")
    if pr_title:
        lines.append(f"# Code Review: PR #{pr_num} — {pr_title}")
    else:
        lines.append(f"# Code Review: PR #{pr_num}")
    lines.append("")

    # Metadata block
    if meta.get("repository"):
        lines.append(f"**Repository**: {meta['repository']}")
    if meta.get("author"):
        lines.append(f"**Author**: {meta['author']}")
    branch = meta.get("branch", {})
    if branch.get("head") and branch.get("base"):
        lines.append(f"**Branch**: {branch['head']} -> {branch['base']}")
    if meta.get("pr_url"):
        lines.append(f"**PR URL**: {meta['pr_url']}")
    # Files changed
    changes_parts = []
    if meta.get("files_changed") is not None:
        changes_parts.append(f"{meta['files_changed']} files changed")
    if meta.get("additions") is not None:
        changes_parts.append(f"{meta['additions']:,} additions")
    if meta.get("deletions") is not None:
        changes_parts.append(f"{meta['deletions']:,} deletions")
    if changes_parts:
        lines.append(f"**Files Changed**: {', '.join(changes_parts)}")
    if meta.get("review_date"):
        lines.append(f"**Review Date**: {meta['review_date']}")
    lines.append("")

    # Summary
    lines.append("---")
    lines.append("")
    summary = review.get("summary", "")
    if summary:
        lines.append("**Summary**")
        lines.append("")
        lines.append(summary)
        lines.append("")

    # Sections
    section_names = get_section_display_names()
    for section in review.get("sections", []):
        sec_type = section.get("type", "")
        display_name = section.get("display_name") or section_names.get(sec_type, sec_type.title())
        issues = section.get("issues", [])

        lines.append("---")
        lines.append("")
        lines.append(f"**{display_name}**")
        lines.append("")

        if not issues:
            lines.append("None")
            lines.append("")
            continue

        for idx, issue in enumerate(issues, 1):
            lines.append(f"**{idx}. {issue.get('title', 'Untitled')}**")
            loc = issue.get("location", {})
            loc_str = loc.get("file", "")
            start = loc.get("start_line")
            end = loc.get("end_line")
            if start is not None and end is not None and start != end:
                loc_str += f":{start}-{end}"
            elif start is not None:
                loc_str += f":{start}"
            if loc_str:
                lines.append(f"- Location: `{loc_str}`")
            if issue.get("problem"):
                lines.append(f"- Problem: {issue['problem']}")
            if issue.get("fix"):
                lines.append(f"- Fix: {issue['fix']}")
            if issue.get("code_snippet"):
                lines.append("")
                lines.append("```")
                lines.append(issue["code_snippet"])
                lines.append("```")
            lines.append("")

    # Highlights
    highlights = review.get("highlights", [])
    if highlights:
        lines.append("---")
        lines.append("")
        lines.append("**Positive Highlights**")
        lines.append("")
        for i, h in enumerate(highlights, 1):
            lines.append(f"{i}. {h}")
        lines.append("")

    # Recommendations
    recs = review.get("recommendations", [])
    if recs:
        lines.append("---")
        lines.append("")
        lines.append("**Recommendations**")
        lines.append("")
        priority_labels = {
            "must_fix": "Must Fix Before Merge:",
            "high": "High Priority:",
            "medium": "Medium Priority:",
            "low": "Low Priority:",
        }
        current_priority = None
        rec_num = 1
        for rec in recs:
            p = rec.get("priority", "medium")
            label = priority_labels.get(p, f"{p.title()}:")
            if p != current_priority:
                if current_priority is not None:
                    lines.append("")
                lines.append(f"**{label}**")
                current_priority = p
            lines.append(f"{rec_num}. {rec.get('text', '')}")
            rec_num += 1
        lines.append("")

    # Score
    score = review.get("score", {})
    if score.get("overall") is not None:
        lines.append("---")
        lines.append("")
        overall = score["overall"]
        # Format as integer if whole number
        if overall == int(overall):
            lines.append(f"**Score: {int(overall)}/10**")
        else:
            lines.append(f"**Score: {overall}/10**")
        lines.append("")
        if score.get("summary"):
            lines.append(score["summary"])
            lines.append("")
        breakdown = score.get("breakdown", [])
        if breakdown:
            for entry in breakdown:
                cat = entry.get("category", "")
                s = entry.get("score", 0)
                comment = entry.get("comment", "")
                if s == int(s):
                    s = int(s)
                line = f"- **{cat}**: {s}/10"
                if comment:
                    line += f" — {comment}"
                lines.append(line)
            lines.append("")

    # Follow-up resolution
    followup = review.get("followup")
    if followup and followup.get("resolution_status"):
        lines.append("---")
        lines.append("")
        lines.append("**Previous Issue Resolution**")
        lines.append("")
        for res in followup["resolution_status"]:
            status_label = res.get("status", "unknown").replace("_", " ").title()
            lines.append(f"- **{res.get('issue', '')}**: {status_label}")
            if res.get("notes"):
                lines.append(f"  - {res['notes']}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Markdown -> JSON  (best-effort parser for migrating existing reviews)
# ---------------------------------------------------------------------------

def markdown_to_json(content: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Parse an existing markdown review into the JSON schema.

    This is a best-effort parser that handles the various markdown formats
    produced by the code-reviewer agent. It reuses proven regex patterns
    from inline_comments_service.py (Location/Problem/Fix) and the frontend's
    reviewSections.ts (section boundary detection).

    Args:
        content: Raw markdown review text.
        metadata: Optional dict with overrides for metadata fields (pr_number, repo, etc.).

    Returns:
        A dict conforming to the review JSON schema.
    """
    if not content:
        return _empty_review(metadata)

    result: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "metadata": _parse_metadata(content, metadata),
        "summary": _parse_summary(content),
        "sections": _parse_sections(content),
        "highlights": _parse_highlights(content),
        "recommendations": _parse_recommendations(content),
        "score": _parse_score(content),
    }

    # Detect follow-up
    followup = _parse_followup(content, metadata)
    if followup:
        result["followup"] = followup

    return result


def _empty_review(metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    meta = metadata or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "metadata": {
            "pr_number": meta.get("pr_number", 0),
            "repository": meta.get("repo", meta.get("repository", "")),
        },
        "summary": "",
        "sections": [
            {"type": "critical", "display_name": "Critical Issues", "issues": []},
            {"type": "major", "display_name": "Major Concerns", "issues": []},
            {"type": "minor", "display_name": "Minor Issues", "issues": []},
        ],
        "highlights": [],
        "recommendations": [],
        "score": {"overall": 0},
    }


def _parse_metadata(content: str, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Extract metadata from the review header."""
    meta: Dict[str, Any] = {}
    ov = overrides or {}

    # PR number from H1: "# Code Review: PR #123" or "# Code Review: PR #123 — Title"
    h1 = re.search(r'^#\s+.*?PR\s*#(\d+)', content, re.MULTILINE | re.IGNORECASE)
    if h1:
        meta["pr_number"] = int(h1.group(1))

    # PR title from H1 after em-dash or colon
    title_match = re.search(r'^#\s+.*?PR\s*#\d+\s*[—–:\-]\s*(.+)', content, re.MULTILINE)
    if title_match:
        meta["pr_title"] = title_match.group(1).strip()

    # Metadata fields with **Label**: value pattern
    field_patterns = {
        "repository": r'\*\*Repository\*?\*?:?\s*(.+)',
        "author": r'\*\*Author\*?\*?:?\s*(.+)',
        "pr_url": r'\*\*PR\s*URL\*?\*?:?\s*(https?\S+)',
        "review_date": r'\*\*Review\s*Date\*?\*?:?\s*(.+)',
    }
    for field, pattern in field_patterns.items():
        m = re.search(pattern, content, re.IGNORECASE)
        if m:
            meta[field] = m.group(1).strip()

    # Branch: head -> base
    branch_match = re.search(r'\*\*Branch\*?\*?:?\s*(\S+)\s*->\s*(\S+)', content, re.IGNORECASE)
    if branch_match:
        meta["branch"] = {
            "head": branch_match.group(1).strip(),
            "base": branch_match.group(2).strip(),
        }

    # Files changed: "6 files changed", "12 new files", etc. and additions/deletions
    changes_match = re.search(
        r'\*\*Files?\s*Changed?\*?\*?:?\s*(.+)',
        content, re.IGNORECASE
    )
    if changes_match:
        changes_text = changes_match.group(1)
        fc = re.search(r'(\d+)\s*(?:files?\s*changed|new)', changes_text, re.IGNORECASE)
        if fc:
            meta["files_changed"] = int(fc.group(1))
        add_m = re.search(r'([\d,]+)\s*addition', changes_text, re.IGNORECASE)
        if add_m:
            meta["additions"] = int(add_m.group(1).replace(",", ""))
        del_m = re.search(r'([\d,]+)\s*deletion', changes_text, re.IGNORECASE)
        if del_m:
            meta["deletions"] = int(del_m.group(1).replace(",", ""))

    # Determine review type
    if ov.get("is_followup"):
        meta["review_type"] = "followup"
    elif re.search(r'follow[- ]?up', content[:500], re.IGNORECASE):
        meta["review_type"] = "followup"
    else:
        meta["review_type"] = "initial"

    # Apply overrides (DB fields take precedence over parsed values)
    if ov.get("pr_number"):
        meta["pr_number"] = ov["pr_number"]
    if ov.get("repo") or ov.get("repository"):
        meta["repository"] = ov.get("repo") or ov.get("repository")
    if ov.get("pr_url"):
        meta["pr_url"] = ov["pr_url"]
    if ov.get("pr_title"):
        meta["pr_title"] = ov["pr_title"]
    if ov.get("pr_author"):
        meta["author"] = ov["pr_author"]

    # Ensure required fields
    meta.setdefault("pr_number", 0)
    meta.setdefault("repository", "")

    return meta


def _parse_summary(content: str) -> str:
    """Extract the summary paragraph."""
    # Look for **Summary** section
    m = re.search(
        r'\*\*Summary\*\*\s*\n+(.*?)(?=\n---|\n\*\*(?:Critical|Major|Minor|Positive|Score|Recommendations))',
        content, re.DOTALL | re.IGNORECASE
    )
    if m:
        return m.group(1).strip()

    # Fallback: text between first --- and second --- (or first section heading)
    parts = re.split(r'\n---\s*\n', content, maxsplit=2)
    if len(parts) >= 2:
        candidate = parts[1].strip()
        # Skip if it starts with a section heading
        if candidate and not re.match(r'\*\*(?:Critical|Major|Minor)', candidate, re.IGNORECASE):
            # Remove leading **Summary** if present
            candidate = re.sub(r'^\*\*Summary\*\*\s*\n*', '', candidate).strip()
            return candidate

    return ""


# Section heading patterns and their types
_SECTION_MAP = {
    "Critical Issues": "critical",
    "Major Concerns": "major",
    "Minor Issues": "minor",
}

# All known section headings that terminate a section (matches frontend reviewSections.ts)
_ALL_HEADINGS = [
    "Critical Issues", "Major Concerns", "Minor Issues",
    "Positive Highlights", "Recommendations", "Summary", "Score",
]


def _parse_sections(content: str) -> List[Dict[str, Any]]:
    """Parse Critical Issues, Major Concerns, Minor Issues sections."""
    sections = []
    display_names = get_section_display_names()

    for heading, sec_type in _SECTION_MAP.items():
        escaped = re.escape(heading)
        # Build terminator pattern from all known headings
        terminators = "|".join(
            rf'\n\*\*{re.escape(h)}\*\*'
            for h in _ALL_HEADINGS if h != heading
        )
        pattern = re.compile(
            rf'\*\*{escaped}\*\*\s*(.*?)(?={terminators}|\n---(?:\s|$)|\n##\s|\Z)',
            re.DOTALL | re.IGNORECASE
        )
        match = pattern.search(content)

        display_name = display_names.get(sec_type, heading)
        if not match or not match.group(1).strip() or match.group(1).strip().lower() == "none":
            sections.append({
                "type": sec_type,
                "display_name": display_name,
                "issues": [],
            })
            continue

        section_text = match.group(1)
        issues = _parse_issues_from_section(section_text)
        sections.append({
            "type": sec_type,
            "display_name": display_name,
            "issues": issues,
        })

    return sections


def _parse_issues_from_section(section_text: str) -> List[Dict[str, Any]]:
    """Parse individual issues from a section block.

    Looks for patterns like:
        **1. Issue Title**
        - Location: `file.py:123-456`
        - Problem: Description
        - Fix: Recommendation
    """
    issues = []
    # Match issue headers: **1. Title** or **N. Title**
    headers = list(re.finditer(r'\*\*(\d+)\.\s*(.+?)\*\*', section_text))

    for idx, header in enumerate(headers):
        title = header.group(2).strip()
        start = header.end()
        end = headers[idx + 1].start() if idx + 1 < len(headers) else len(section_text)
        block = section_text[start:end]

        location_str = _extract_field(block, "Location")
        problem = _extract_field(block, "Problem")
        fix = _extract_field(block, "Fix")

        loc = _parse_location_string(location_str)
        if not loc:
            loc = {"file": location_str or "", "start_line": None, "end_line": None}

        issue: Dict[str, Any] = {
            "title": title,
            "location": loc,
            "problem": problem or "",
        }
        if fix:
            issue["fix"] = fix

        # Extract code snippets
        code_match = re.search(r'```[\w]*\n(.*?)```', block, re.DOTALL)
        if code_match:
            issue["code_snippet"] = code_match.group(1).strip()

        issues.append(issue)

    return issues


def _extract_field(block: str, field_name: str) -> Optional[str]:
    """Extract a field from an issue block (e.g. '- Location: value')."""
    pattern = re.compile(
        rf'-\s*{field_name}:\s*(.*?)(?=\n-\s*(?:Location|Problem|Fix):|\n\*\*\d+\.|\n```|\Z)',
        re.DOTALL
    )
    m = pattern.search(block)
    if m:
        return m.group(1).strip()
    return None


def _parse_location_string(loc_str: Optional[str]) -> Optional[Dict[str, Any]]:
    """Parse a location string like '`file.py:123-456`' into structured data."""
    if not loc_str:
        return None

    # Pattern: `file.py:123-456` or `file.py:123` or file.py:123-456
    m = re.match(r'`?([^`:\s]+)`?\s*:\s*(\d+)(?:\s*-\s*(\d+))?', loc_str)
    if m:
        return {
            "file": m.group(1).strip(),
            "start_line": int(m.group(2)),
            "end_line": int(m.group(3)) if m.group(3) else int(m.group(2)),
        }

    # Pattern: `file.py` with separate line reference
    path_m = re.match(r'`([^`]+)`', loc_str)
    if path_m:
        file_path = path_m.group(1).strip()
        line_m = re.search(r'lines?\s+(\d+)\s*[-–]\s*(\d+)', loc_str)
        if line_m:
            return {
                "file": file_path,
                "start_line": int(line_m.group(1)),
                "end_line": int(line_m.group(2)),
            }
        line_m = re.search(r'line\s+(\d+)', loc_str)
        if line_m:
            return {
                "file": file_path,
                "start_line": int(line_m.group(1)),
                "end_line": int(line_m.group(1)),
            }
        return {"file": file_path, "start_line": None, "end_line": None}

    # Bare path with colon-line
    bare_m = re.match(r'(\S+):(\d+)(?:-(\d+))?', loc_str)
    if bare_m:
        return {
            "file": bare_m.group(1).strip(),
            "start_line": int(bare_m.group(2)),
            "end_line": int(bare_m.group(3)) if bare_m.group(3) else int(bare_m.group(2)),
        }

    return None


def _parse_highlights(content: str) -> List[str]:
    """Parse the Positive Highlights section."""
    m = re.search(
        r'\*\*Positive Highlights\*\*\s*\n+(.*?)(?=\n---|\n\*\*(?:Recommendations|Score)\*\*|\Z)',
        content, re.DOTALL | re.IGNORECASE
    )
    if not m:
        return []

    highlights = []
    for line in m.group(1).strip().split("\n"):
        line = line.strip()
        # Match numbered items: "1. text" or "- text"
        item = re.match(r'^\d+\.\s*(?:\*\*.*?\*\*:?\s*)?(.+)', line)
        if item:
            highlights.append(item.group(1).strip() if not line.startswith(("**", "- **")) else line.lstrip("0123456789. "))
            continue
        item = re.match(r'^[-*]\s+(.+)', line)
        if item:
            highlights.append(item.group(1).strip())
            continue
        # Continuation of previous highlight
        if line and highlights:
            highlights[-1] += " " + line

    # Clean up: collapse numbered highlights that include bold prefix
    cleaned = []
    for h in highlights:
        # Remove leading bold marker if the whole item was "1. **Bold**: rest"
        cleaned.append(h)
    return cleaned


def _parse_recommendations(content: str) -> List[Dict[str, str]]:
    """Parse the Recommendations section into prioritized list."""
    m = re.search(
        r'\*\*Recommendations\*\*\s*\n+(.*?)(?=\n---|\n\*\*(?:Score|Positive)\*\*|\Z)',
        content, re.DOTALL | re.IGNORECASE
    )
    if not m:
        return []

    recs = []
    current_priority = "medium"
    text = m.group(1).strip()

    priority_map = {
        "must fix": "must_fix",
        "must fix before merge": "must_fix",
        "high priority": "high",
        "high": "high",
        "medium priority": "medium",
        "medium": "medium",
        "low priority": "low",
        "low": "low",
    }

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue

        # Check for priority header: **Must Fix Before Merge:**
        priority_match = re.match(r'\*\*(.+?)(?::|\*\*)', line)
        if priority_match:
            label = priority_match.group(1).strip().rstrip(":").lower()
            if label in priority_map:
                current_priority = priority_map[label]
                # Check if there's text after the priority on the same line
                remainder = line[priority_match.end():].strip().lstrip(":").lstrip("*").strip()
                if remainder:
                    # It might be a numbered item
                    item_m = re.match(r'^\d+\.\s*(.*)', remainder)
                    if item_m:
                        recs.append({"priority": current_priority, "text": item_m.group(1).strip()})
                continue

        # Numbered item: "1. Fix the thing"
        item_m = re.match(r'^\d+\.\s*(.*)', line)
        if item_m:
            recs.append({"priority": current_priority, "text": item_m.group(1).strip()})
            continue

        # Bullet item: "- Fix the thing"
        item_m = re.match(r'^[-*]\s+(.*)', line)
        if item_m:
            recs.append({"priority": current_priority, "text": item_m.group(1).strip()})

    return recs


def _parse_score(content: str) -> Dict[str, Any]:
    """Extract the score section from review markdown."""
    score: Dict[str, Any] = {"overall": 0}

    # Match patterns: "Score: 8/10", "**Score: 8/10**", "## Score: 8/10"
    patterns = [
        r'(?:#*\s*)?(?:\*\*)?(?:\w+\s+)?(?:Score|Rating)\s*[:\s]*(\d+(?:\.\d{1,2})?)\s*/?\s*10',
        r'(\d+(?:\.\d{1,2})?)\s*/\s*10\s*(?:score|rating)',
    ]
    for pattern in patterns:
        m = re.search(pattern, content, re.IGNORECASE)
        if m:
            val = float(m.group(1))
            if 0 <= val <= 10:
                score["overall"] = val
                break

    # Try to find score summary text after the score line
    score_section = re.search(
        r'\*\*Score:.*?\*\*\s*\n+(.*?)(?=\n---|\n\*\*|\Z)',
        content, re.DOTALL | re.IGNORECASE
    )
    if score_section:
        summary_text = score_section.group(1).strip()
        # Separate summary text from breakdown items
        summary_lines = []
        breakdown = []
        for line in summary_text.split("\n"):
            line = line.strip()
            bd_match = re.match(r'^-\s*\*\*(.+?)\*\*:\s*(\d+(?:\.\d+)?)/10(?:\s*[—–-]\s*(.+))?', line)
            if bd_match:
                entry: Dict[str, Any] = {
                    "category": bd_match.group(1).strip(),
                    "score": float(bd_match.group(2)),
                }
                if bd_match.group(3):
                    entry["comment"] = bd_match.group(3).strip()
                breakdown.append(entry)
            elif line:
                summary_lines.append(line)

        if summary_lines:
            score["summary"] = " ".join(summary_lines)
        if breakdown:
            score["breakdown"] = breakdown

    return score


def _parse_followup(content: str, metadata: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Parse follow-up resolution status if present."""
    ov = metadata or {}
    if not ov.get("is_followup") and not re.search(r'follow[- ]?up|previous\s+(?:review|issue)', content[:500], re.IGNORECASE):
        return None

    followup: Dict[str, Any] = {
        "previous_review_id": ov.get("parent_review_id"),
        "resolution_status": [],
    }

    # Look for resolution items: "- **Issue text**: Resolved" or similar
    res_pattern = re.compile(
        r'-\s*\*\*(.+?)\*\*:\s*(resolved|partially[\s_]addressed|not[\s_]addressed|wont[\s_]fix)(?:\s*[-–]\s*(.+))?',
        re.IGNORECASE
    )
    for m in res_pattern.finditer(content):
        status = m.group(2).strip().lower().replace(" ", "_").replace("-", "_")
        entry: Dict[str, Any] = {"issue": m.group(1).strip(), "status": status}
        if m.group(3):
            entry["notes"] = m.group(3).strip()
        followup["resolution_status"].append(entry)

    return followup if followup["resolution_status"] or followup["previous_review_id"] else None
