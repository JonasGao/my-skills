#!/usr/bin/env python3
"""Wait for one terminal reply and print it as JSON on stdout."""

import argparse
import math
import sys

from _reply_protocol import ProtocolError, output_record, route_for, wait_for_record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request_id")
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="optional deadline in seconds from waiter start (default: infinite)",
    )
    parser.add_argument("--temp-dir", help="override the system temporary directory (for tests)")
    args = parser.parse_args()
    if args.timeout is not None and (not math.isfinite(args.timeout) or args.timeout < 0):
        print("Error: --timeout must be a finite non-negative number", file=sys.stderr)
        return 2
    try:
        route = route_for(args.request_id, args.temp_dir)
        output_record(wait_for_record(route, args.request_id, args.timeout))
    except ProtocolError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
