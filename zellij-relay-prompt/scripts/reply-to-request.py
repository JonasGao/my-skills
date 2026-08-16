#!/usr/bin/env python3
"""Submit a succeeded or failed terminal reply for a request."""

import argparse
import json
import sys

from _reply_protocol import (
    ProtocolError,
    REPLY_NAME,
    RECEIVER_STATUSES,
    atomic_write,
    make_record,
    output_record,
    read_result,
    read_summary,
    read_record,
    route_for,
    state_lock,
    write_result,
    wake,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request_id")
    parser.add_argument("status", choices=sorted(RECEIVER_STATUSES))
    parser.add_argument("summary_file", nargs="?", help="UTF-8 summary file (at most 4 KiB)")
    parser.add_argument("result_file", nargs="?", help="optional complete result file")
    parser.add_argument("--summary-file", dest="summary_option")
    parser.add_argument("--result-file", dest="result_option")
    parser.add_argument("--temp-dir", help="override the system temporary directory (for tests)")
    args = parser.parse_args()
    summary_path = args.summary_option or args.summary_file
    result_path = args.result_option or args.result_file
    if not summary_path:
        print("Error: a summary file is required", file=sys.stderr)
        return 2
    try:
        route = route_for(args.request_id, args.temp_dir)
        summary = read_summary(summary_path)
        result = read_result(result_path)
        result_destination = str(route / "result.bin") if result is not None else None
        candidate = make_record(args.request_id, args.status, summary, result, result_destination)
        with state_lock(route):
            existing = read_record(route)
            if existing is not None:
                if existing.get("content_sha256") == candidate.get("content_sha256"):
                    output_record(existing)
                    return 0
                print("Error: request already has a different terminal reply", file=sys.stderr)
                return 1
            if result is not None:
                write_result(route, result)
            # The record is the commit point; write it atomically while the
            # state lock excludes cancellation and timeout writers.
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
