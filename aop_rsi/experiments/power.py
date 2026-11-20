"""How big an improvement can n cases detect?

Paired comparison of two versions on the same n cases, pass/fail per case.
`d` is the share of cases on which the two versions disagree; `delta` is the
true net gain (so d >= delta). Normal approximation to the paired test.

    python -m aop_rsi.experiments.power             # the table in STATUS.md
    python -m aop_rsi.experiments.power 150 0.12    # one n and one d

Use it before trusting any before/after comparison: if the gain you hope for is
smaller than what your case count can detect, the comparison cannot settle it.
"""
from __future__ import annotations

import sys
from math import ceil, sqrt
from statistics import NormalDist


def _z(alpha: float, power: float) -> float:
    q = NormalDist().inv_cdf
    return q(1 - alpha / 2) + q(power)


def min_detectable_gain(n: int, d: float, alpha: float = 0.05, power: float = 0.80) -> float:
    """Smallest true gain detectable: solves delta = z * sqrt((d - delta^2) / n)."""
    if not 0 < d <= 1:
        raise ValueError("d must be in (0, 1]")
    z = _z(alpha, power)
    return z * sqrt(d / (n + z * z))


def cases_needed(delta: float, d: float, alpha: float = 0.05, power: float = 0.80) -> int:
    """Paired cases needed to detect a true gain of `delta` when the versions disagree on share `d`."""
    if not 0 < delta <= d <= 1:
        raise ValueError("need 0 < delta <= d <= 1")
    z = _z(alpha, power)
    return ceil(z * z * (d - delta * delta) / (delta * delta))


def main(argv: list[str]) -> None:
    if len(argv) == 2:
        n, d = int(argv[0]), float(argv[1])
        print(f"n={n}, d={d:.2f}: smallest detectable gain = {100 * min_detectable_gain(n, d):.1f} points")
        return
    ds = (0.10, 0.15, 0.20)
    print("Smallest real gain detectable (points), 80% power, 5% two-sided, paired on the same cases")
    print("  n      " + "   ".join(f"d={d:.2f}" for d in ds))
    for n in (100, 200, 400, 1000, 2000):
        print(f"  {n:<6d} " + "   ".join(f"{100 * min_detectable_gain(n, d):6.1f}" for d in ds))
    print("\nCases needed to detect a gain of")
    for delta in (0.02, 0.03, 0.05, 0.10):
        print(f"  {100 * delta:4.0f} points: " + "   ".join(f"d={d:.2f}: {cases_needed(delta, d):5d}" for d in (0.10, 0.15)))


if __name__ == "__main__":
    main(sys.argv[1:])
