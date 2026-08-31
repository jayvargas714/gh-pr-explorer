#!/usr/bin/env python3
"""Seed the automation routing config with a starter ruleset.

The shipped seed (scripts/automation_seed.json) carries the internal Scala
convention — PB-* files route to the PB reviewer, ED-* files to the ED
reviewer, the PB/ED index files are ignored, and everything else falls back to
the default (elite) reviewer. Other installations can copy and edit the JSON.

The seed is inert on its own: scope stays "off" and the repo allowlist stays
empty, so seeding never starts dispatching — the operator still enables
automation in the tab.

Usage:
    python scripts/seed_automation_config.py             # seed if unconfigured
    python scripts/seed_automation_config.py --force     # overwrite existing config
    python scripts/seed_automation_config.py --file my_ruleset.json
"""

import argparse
import json
import sys
from pathlib import Path

# Add project root to path so we can import backend modules
sys.path.insert(0, str(Path(__file__).parent.parent))

DEFAULT_SEED_FILE = Path(__file__).parent / "automation_seed.json"


def seed(payload, force=False):
    """Validate and store the automation config. Returns True when written.

    Refuses to touch an existing config unless force=True (a forced seed
    replaces the whole blob, including scope and repo allowlist).
    Raises ValueError when the payload fails validation.
    """
    from backend.database import get_reviewers_db, get_settings_db
    from backend.services import automation_config

    existing = get_settings_db().get_setting(automation_config.SETTINGS_KEY)
    if existing is not None and not force:
        return False

    valid_keys = [r["key"] for r in get_reviewers_db().list_reviewers()]
    automation_config.save_config(payload, valid_keys)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", type=Path, default=DEFAULT_SEED_FILE,
                        help=f"Ruleset JSON to install (default: {DEFAULT_SEED_FILE.name})")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite an existing config (replaces the whole blob, "
                             "including scope and repo allowlist)")
    args = parser.parse_args()

    payload = json.loads(args.file.read_text())
    try:
        written = seed(payload, force=args.force)
    except ValueError as e:
        print(f"Seed rejected: {e}", file=sys.stderr)
        return 1

    if not written:
        print("Automation config already exists — nothing changed. "
              "Re-run with --force to overwrite it.")
        return 1

    rules = ", ".join(f"{r['name']} -> {r['reviewerKey']}" for r in payload.get("rules", []))
    print(f"Seeded automation config from {args.file.name}: "
          f"rules [{rules}], default -> {payload['defaultRule']['reviewerKey']}, "
          f"scope {payload.get('scope', 'off')}.")
    print("Automation stays off until a scope and repo allowlist are set in the Automation tab.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
