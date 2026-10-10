#!/usr/bin/env python3
"""Independent M3 image oracle using exact rational complex coordinates."""
import hashlib
import json
from fractions import Fraction
from math import floor, trunc
from pathlib import Path


def render(rounding):
    pixels = []
    fractional_negative_products = 0
    for y in range(12):
        for x in range(16):
            cx = Fraction(-2) + Fraction(x, 4)
            cy = Fraction(-3, 2) + Fraction(y, 4)
            real = imaginary = Fraction(0)
            count = 0
            while count < 16:
                real_squared = Fraction(rounding(real * real * 256), 256)
                imaginary_squared = Fraction(rounding(imaginary * imaginary * 256), 256)
                if real_squared + imaginary_squared >= 4:
                    break
                cross = real * imaginary * 256
                fractional_negative_products += int(cross < 0 and cross.denominator != 1)
                real, imaginary = (
                    real_squared - imaginary_squared + cx,
                    2 * Fraction(rounding(cross), 256) + cy,
                )
                count += 1
            pixels.append(count)
    return bytes(pixels), fractional_negative_products


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    expected, negative_products = render(floor)
    truncated, _ = render(trunc)
    checked = []
    for name in ("cos-128.bin", "cos-64.bin", "native-128.bin", "native-64.bin"):
        actual = (root / name).read_bytes()
        if actual != expected:
            raise SystemExit(f"Complete image mismatch: {name}")
        checked.append(name)
    print(json.dumps(dict(
        oracle="Exact rational coordinates, Q8.8 quantization after each product",
        pixels=len(expected), iterations=sum(expected),
        sha256=hashlib.sha256(expected).hexdigest(),
        negative_nonintegral_cross_products=negative_products,
        truncation_changed_pixels=sum(a != b for a, b in zip(expected, truncated)),
        checked=checked,
    ), indent=2))
