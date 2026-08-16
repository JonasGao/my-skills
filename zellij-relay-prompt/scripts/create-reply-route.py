#!/usr/bin/env python3
"""Create a private tracked-delegation reply route."""

import argparse
import sys

from _reply_protocol import ProtocolError, create_route, output_record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--temp-dir", help="override the system temporary directory (for tests)")
    args = parser.parse_args()
    try:
        output_record(create_route(args.temp_dir))
    except ProtocolError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
