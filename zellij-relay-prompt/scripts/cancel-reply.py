#!/usr/bin/env python3
"""Cancel an open tracked-delegation reply request."""

import argparse
import json
import sys

from _reply_protocol import (
    ProtocolError,
    REPLY_NAME,
    atomic_write,
    make_record,
    output_record,
    read_record,
    read_summary,
    route_for,
    state_lock,
    wake,
)


DEFAULT_SUMMARY = "Reply request cancelled by sender."


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request_id")
    parser.add_argument("summary_file", nargs="?", help="optional UTF-8 cancellation summary file")
    parser.add_argument("--summary-file", dest="summary_option")
    parser.add_argument("--temp-dir", help="override the system temporary directory (for tests)")
    args = parser.parse_args()
    try:
        route = route_for(args.request_id, args.temp_dir)
        summary = (
            read_summary(args.summary_option or args.summary_file)
            if (args.summary_option or args.summary_file)
            else DEFAULT_SUMMARY
        )
        candidate = make_record(args.request_id, "cancelled", summary, None, None)
        with state_lock(route):
            existing = read_record(route)
            if existing is not None:
                if existing.get("content_sha256") == candidate.get("content_sha256"):
                    output_record(existing)
                    return 0
                print("Error: request already has a different terminal reply", file=sys.stderr)
                return 1
            atomic_write(
                route / REPLY_NAME,
                json.dumps(candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            )
        wake(route)
        output_record(candidate)
    except ProtocolError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
