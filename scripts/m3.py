#!/usr/bin/env python3
"""Build an autonomous M3 pack through the established Rust linker and M2 helpers."""
import argparse
import os
from pathlib import Path
import sys

import m2


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest",type=Path,required=True)
    parser.add_argument("--out",type=Path,default=m2.ROOT/"build/m3/128")
    parser.add_argument("--cache-line",type=int,choices=[64,128],default=128)
    parser.add_argument("--extended-diagnostics",action="store_true",
                        help="Enable detailed counters without changing autonomous scheduling")
    parser.add_argument("--margin-hook",action="store_true",
                        help="Build the idle margin hook; execution remains unqualified")
    parser.add_argument("--line-delay",type=int,default=140)
    parser.add_argument("--kickass",default=os.environ.get("KICKASS_JAR",m2.ROOT/"toolchain/KickAss.jar"))
    parser.add_argument("--java",default=os.environ.get("JAVA","java"))
    parser.add_argument("--offline",action="store_true")
    parser.add_argument("--skip-host-build",action="store_true")
    parser.add_argument("--require-numeric-fit",action="store_true",
                        help="Fail after publishing the map if the future 4 KiB numeric target cannot fit")
    args=parser.parse_args()
    args.milestone="m3"
    if not 1<=args.line_delay<=255:
        parser.error("line delay must be 1..255")
    try:
        report=m2.build(args)
        if (report["normal_build"] or args.require_numeric_fit) and report["numeric_target_shortfall"]:
            raise ValueError(f"Future numeric target exceeds resident headroom by {report['numeric_target_shortfall']} bytes")
    except (ValueError,OSError,KeyError) as error:
        print(f"m3: {error}",file=sys.stderr)
        return 1
    return 0


if __name__=="__main__":
    raise SystemExit(main())
