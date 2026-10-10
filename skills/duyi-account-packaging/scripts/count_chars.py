#!/usr/bin/env python3
"""Count characters and line breaks from text, a file, or standard input."""

import argparse
import json
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--text", help="text to count")
    source.add_argument("--file", metavar="PATH", help="UTF-8 text file to count")
    source.add_argument("--stdin", action="store_true", help="read text from standard input")
    parser.add_argument("--min", dest="minimum", type=int, help="optional non-negative minimum character count")
    parser.add_argument("--limit", type=int, help="optional non-negative character limit")
    parser.add_argument(
        "--unit",
        choices=("codepoint", "utf16"),
        default="codepoint",
        help="unit used for count (default: codepoint)",
    )
    args = parser.parse_args()

    if args.minimum is not None and args.minimum < 0:
        parser.error("--min must be non-negative")
    if args.limit is not None and args.limit < 0:
        parser.error("--limit must be non-negative")
    if args.minimum is not None and args.limit is not None and args.minimum > args.limit:
        parser.error("--min must be less than or equal to --limit")

    try:
        if args.text is not None:
            text = args.text
        elif args.file is not None:
            with open(args.file, "r", encoding="utf-8", newline="") as stream:
                text = stream.read()
        else:
            text = sys.stdin.read()
    except (OSError, UnicodeError) as exc:
        parser.error(f"cannot read input: {exc}")

    characters = len(text)
    utf16_units = len(text.encode("utf-16-le")) // 2
    count = characters if args.unit == "codepoint" else utf16_units
    minimum = args.minimum
    limit = args.limit
    within_minimum = None if minimum is None else count >= minimum
    within_limit = None if limit is None else count <= limit
    within_range = None if minimum is None and limit is None else (
        (minimum is None or count >= minimum) and (limit is None or count <= limit)
    )
    result = {
        "characters": characters,
        "utf16_units": utf16_units,
        "newlines": text.count("\n"),
        "unit": args.unit,
        "count": count,
        "minimum": minimum,
        "limit": limit,
        "within_minimum": within_minimum,
        "within_range": within_range,
        "within_limit": within_limit,
        "margin": None if limit is None else limit - count,
    }
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if within_range is None or within_range else 1


if __name__ == "__main__":
    raise SystemExit(main())
