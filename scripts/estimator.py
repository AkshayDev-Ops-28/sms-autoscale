"""
Calibrated execution-time model and pod-sizing logic.

Model (valid for 1-3 pods on the 4-core node, plugged in, apps closed):

    S(n, k) = S0 * (1 + RR * n) * (1 + BETA * k)

    n = other requests in flight on the same pod
    k = other pods that are busy
    S = mean execution time (ms)

Deadlines are sized on p95 = P95_RATIO * mean.

Sizing logic (one rule, no tuning):
    1. For N pods, assume the worst case: k = N - 1 neighbours busy.
    2. n_max(N) = largest n with p95(S) <= deadline.
    3. Per-pod rate at that point (Little's law): lam(N) = (n_max + 1) / S_mean.
    4. Capacity(N) = N * lam(N).  Keep a headroom factor for the open-loop gap.
    5. Pods needed = smallest N whose capacity covers the rate, capped at MAX_PODS.
"""
import math

# ---- calibration constants (single place to change) ----
S0_MS = 52.0          # idle single-request time, mean of 4 plugged-in k=0 samples
RR = 2.2              # per-extra-request slowdown, fitted slope ~117 ms / S0
BETA = 0.25           # per-busy-neighbour slowdown (measured 0.12-0.27, conservative end)
P95_RATIO = 1.6       # measured p95 / mean
MAX_PODS = 3          # 4 busy pods on the 4-core node gave 3.6x-5x latency
DEADLINE_MS = 1000.0  # normal-class deadline
HEADROOM = 0.9        # open-loop safety factor (closed-loop calibration)


def exec_time_ms(n: int, k: int) -> float:
    """Predicted mean execution time."""
    return S0_MS * (1 + RR * n) * (1 + BETA * k)


def p95_ms(n: int, k: int) -> float:
    return P95_RATIO * exec_time_ms(n, k)


def n_max(k: int, deadline_ms: float = DEADLINE_MS) -> int:
    """Largest in-flight-others count n for which p95 still meets the deadline."""
    bound = (deadline_ms / (P95_RATIO * S0_MS * (1 + BETA * k)) - 1) / RR
    return max(0, math.floor(bound))


def pod_rate(k: int, deadline_ms: float = DEADLINE_MS) -> float:
    """Sustainable req/s of one pod when k neighbours are busy (Little's law)."""
    n = n_max(k, deadline_ms)
    return (n + 1) / (exec_time_ms(n, k) / 1000.0)


def capacity(pods: int, deadline_ms: float = DEADLINE_MS) -> float:
    """Request rate N pods can serve within the deadline, with headroom."""
    return HEADROOM * pods * pod_rate(pods - 1, deadline_ms)


def pods_needed(rate_rps: float, deadline_ms: float = DEADLINE_MS) -> int:
    for pods in range(1, MAX_PODS + 1):
        if rate_rps <= capacity(pods, deadline_ms):
            return pods
    return MAX_PODS


def keda_threshold(deadline_ms: float = DEADLINE_MS) -> float:
    """Flat per-pod rate for KEDA's AverageValue: the worst (smallest) per-pod
    capacity over 1..MAX_PODS pods, so replicas = ceil(rate / threshold) never
    under-provisions anywhere in the supported range."""
    return min(capacity(p, deadline_ms) / p for p in range(1, MAX_PODS + 1))


if __name__ == "__main__":
    print(f"Model: S = {S0_MS:g} ms x (1 + {RR:g} n) x (1 + {BETA:g} k), "
          f"p95 = {P95_RATIO:g} x mean, deadline {DEADLINE_MS:g} ms\n")
    print("pods  k  n_max  pod_rate  capacity  (headroom %.0f%%)" % (HEADROOM * 100))
    for p in range(1, MAX_PODS + 1):
        k = p - 1
        print(f"{p:>4} {k:>2} {n_max(k):>6} {pod_rate(k):>8.1f} {capacity(p):>9.1f}")
    print(f"\nKEDA per-pod threshold: {keda_threshold():.1f} req/s")
    print(f"Max servable rate ({MAX_PODS} pods): {capacity(MAX_PODS):.1f} req/s")
    print("\nrate -> pods")
    for r in (4, 8, 10, 14, 16, 18, 20, 24):
        print(f"{r:>4} req/s -> {pods_needed(r)}")
    print("\nUrgent class (250 ms):")
    for p in range(1, MAX_PODS + 1):
        print(f"  k={p-1}: n_max={n_max(p-1, 250)}, p95 at n=0: {p95_ms(0, p-1):.0f} ms")