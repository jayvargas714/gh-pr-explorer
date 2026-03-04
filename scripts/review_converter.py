#!/usr/bin/env python3
"""Bidirectional CLI converter between review JSON and Markdown formats.

Usage:
    # JSON to Markdown
    python scripts/review_converter.py to-md review.json              # stdout
    python scripts/review_converter.py to-md review.json -o review.md # to file
    python scripts/review_converter.py to-md --dir /path/to/jsons     # batch

    # Markdown to JSON
    python scripts/review_converter.py to-json review.md              # stdout
    python scripts/review_converter.py to-json review.md -o review.json
    python scripts/review_converter.py to-json --dir /path/to/mds     # batch
"""

import argparse
import json
import sys
from pathlib import Path

# Add project root to path so we can import backend modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.services.review_schema import (
    json_to_markdown,
    markdown_to_json,
    validate_review_json,
)


def to_markdown(args):
    """Convert JSON review file(s) to markdown."""
    if args.dir:
        dir_path = Path(args.dir)
        if not dir_path.is_dir():
            print(f"Error: {args.dir} is not a directory", file=sys.stderr)
            sys.exit(1)
        files = sorted(dir_path.glob("*.json"))
        if not files:
            print(f"No .json files found in {args.dir}", file=sys.stderr)
            sys.exit(1)
        for f in files:
            out_path = f.with_suffix(".md")
            data = json.loads(f.read_text(encoding="utf-8"))
            md = json_to_markdown(data)
            out_path.write_text(md, encoding="utf-8")
            print(f"  {f.name} -> {out_path.name}")
        print(f"Converted {len(files)} file(s)")
        return

    if not args.input:
        print("Error: provide an input file or --dir", file=sys.stderr)
        sys.exit(1)

    input_path = Path(args.input)
    data = json.loads(input_path.read_text(encoding="utf-8"))
    md = json_to_markdown(data)

    if args.output:
        Path(args.output).write_text(md, encoding="utf-8")
        print(f"Written to {args.output}")
    else:
        print(md)


def to_json(args):
    """Convert markdown review file(s) to JSON."""
    if args.dir:
        dir_path = Path(args.dir)
        if not dir_path.is_dir():
            print(f"Error: {args.dir} is not a directory", file=sys.stderr)
            sys.exit(1)
        files = sorted(dir_path.glob("*.md"))
        if not files:
            print(f"No .md files found in {args.dir}", file=sys.stderr)
            sys.exit(1)
        total = 0
        warnings = 0
        for f in files:
            out_path = f.with_suffix(".json")
            content = f.read_text(encoding="utf-8")
            result = markdown_to_json(content)
            valid, errs = validate_review_json(result)
            if not valid:
                print(f"  WARNING {f.name}: {len(errs)} validation issue(s)")
                for e in errs:
                    print(f"    - {e}")
                warnings += 1
            out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"  {f.name} -> {out_path.name}")
            total += 1
        print(f"Converted {total} file(s), {warnings} with warnings")
        return

    if not args.input:
        print("Error: provide an input file or --dir", file=sys.stderr)
        sys.exit(1)

    input_path = Path(args.input)
    content = input_path.read_text(encoding="utf-8")
    result = markdown_to_json(content)

    valid, errs = validate_review_json(result)
    if not valid:
        print(f"Validation warnings:", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)

    output = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Written to {args.output}")
    else:
        print(output)


def main():
    parser = argparse.ArgumentParser(description="Review format converter (JSON <-> Markdown)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # to-md subcommand
    md_parser = subparsers.add_parser("to-md", help="Convert JSON to Markdown")
    md_parser.add_argument("input", nargs="?", help="Input JSON file")
    md_parser.add_argument("-o", "--output", help="Output markdown file")
    md_parser.add_argument("--dir", help="Batch convert all .json files in directory")
    md_parser.set_defaults(func=to_markdown)

    # to-json subcommand
    json_parser = subparsers.add_parser("to-json", help="Convert Markdown to JSON")
    json_parser.add_argument("input", nargs="?", help="Input markdown file")
    json_parser.add_argument("-o", "--output", help="Output JSON file")
    json_parser.add_argument("--dir", help="Batch convert all .md files in directory")
    json_parser.set_defaults(func=to_json)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
