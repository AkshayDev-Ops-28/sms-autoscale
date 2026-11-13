"""Calibrate S0 and RR for S = S0 * (1 + n*RR) on ONE idle sms-spam pod.
With C closed-loop clients there are always C requests in flight => n = C-1."""
import argparse, csv, os, random, threading, time
import requests


def worker(url, corpus, stop_at, warm_until, out):
    s = requests.Session()
    while time.perf_counter() < stop_at:
        t0 = time.perf_counter()
        r = s.post(url, json={"text": random.choice(corpus)}, timeout=30)
        dt = time.perf_counter() - t0
        if r.status_code == 200 and t0 >= warm_until:
            out.append(dt)


def run_level(url, corpus, c, duration, warmup):
    out, now = [], time.perf_counter()
    stop_at, warm_until = now + duration, now + warmup
    ts = [threading.Thread(target=worker, args=(url, corpus, stop_at, warm_until, out))
          for _ in range(c)]
    [t.start() for t in ts]; [t.join() for t in ts]
    out.sort()
    return {"C": c, "n": c - 1, "count": len(out),
            "mean_s": sum(out) / len(out),
            "p95_s": out[int(0.95 * (len(out) - 1))],
            "rps": len(out) / (duration - warmup)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8080/classify")
    ap.add_argument("--corpus", default=os.path.join("data", "sms_sample.txt"))
    ap.add_argument("--levels", type=int, nargs="+", default=[1, 2, 4, 8])
    ap.add_argument("--duration", type=int, default=60)
    ap.add_argument("--warmup", type=int, default=10)
    a = ap.parse_args()

    corpus = [l.strip() for l in open(a.corpus, encoding="utf-8") if l.strip()]
    for _ in range(20):                       # warm the pod
        requests.post(a.url, json={"text": corpus[0]}, timeout=30)

    rows = []
    for c in a.levels:
        r = run_level(a.url, corpus, c, a.duration, a.warmup)
        rows.append(r)
        print(f"C={c:>2} n={r['n']:>2} mean={r['mean_s']*1000:7.1f} ms "
              f"p95={r['p95_s']*1000:7.1f} ms rps={r['rps']:.1f}")

    # least-squares fit: mean = a + b*n  ->  S0 = a, RR = b/a
    xs, ys = [r["n"] for r in rows], [r["mean_s"] for r in rows]
    xm, ym = sum(xs) / len(xs), sum(ys) / len(ys)
    b = sum((x - xm) * (y - ym) for x, y in zip(xs, ys)) / sum((x - xm) ** 2 for x in xs)
    a0 = ym - b * xm
    mae = sum(abs((a0 + b * x) - y) for x, y in zip(xs, ys)) / len(xs)
    print(f"\nS0 = {a0*1000:.1f} ms   RR = {b/a0:.3f}   fit MAE = {mae*1000:.1f} ms")

    os.makedirs("results", exist_ok=True)
    with open(os.path.join("results", "calibration.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) + ["S0_s", "RR"])
        w.writeheader()
        for r in rows:
            w.writerow({**r, "S0_s": a0, "RR": b / a0})


if __name__ == "__main__":
    main()