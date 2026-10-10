#!/usr/bin/env python3
"""Independent integer reference for the exact M3 image computation profile."""
import argparse
import hashlib
import json
from pathlib import Path

WIDTH, HEIGHT, LIMIT = 16, 12, 16


def image(width=WIDTH, height=HEIGHT, limit=LIMIT, step=64):
    result = bytearray()
    iterations = 0
    for y in range(height):
        cy = -384 + step*y
        for x in range(width):
            cx = -512 + step*x
            zx = zy = count = 0
            while count < limit:
                # Python integers retain the exact signed product; // rounds
                # toward negative infinity, matching signed product >>8.
                xx, yy = zx*zx//256, zy*zy//256
                assert xx+yy < 65536
                if xx+yy >= 1024:
                    break
                zy = 2*(zx*zy//256)+cy
                zx = xx-yy+cx
                assert -32768 <= zx <= 32767 and -32768 <= zy <= 32767
                count += 1
            iterations += count
            result.append(count)
    return bytes(result), iterations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    output, iterations = image()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(output)
    print(json.dumps(dict(width=WIDTH,height=HEIGHT,limit=LIMIT,
        arithmetic='signed Q8.8; full product floor-divided by256',
        viewport=dict(cx_first=-512,cy_first=-384,step=64),
        bytes=len(output),iterations=iterations,sha256=hashlib.sha256(output).hexdigest()),indent=2))


if __name__ == '__main__':
    main()
