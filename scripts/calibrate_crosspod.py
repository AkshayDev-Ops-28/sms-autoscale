"""Cross-pod interference: latency of a probe pod (n=0) while k other pods are saturated.
ports[0] = probe pod; ports[1:] = background pods (one port-forward per pod)."""
import argparse, csv, multiprocessing as mp, os, random, threading, time
import requests


def _worker(url, corpus, stop_at, warm_until, out):
    s = requests.Session()
    while time.time() < stop_at:
        t0w, t0 = time.time(), time.perf_counter()
        try:
            r = s.post(url, json={"text": random.choice(corpus)}, timeout=30)
        except requests.RequestException:
            continue
        dt = time.perf_counter() - t0
        if r.status_code == 200 and t0w >= warm_until:
            out.append(dt)


def _pod_proc(tag, port, clients, corpus, stop_at, warm_until, q):
    url = f"http://localhost:{port}/classify"
    out = []
    ts = [threading.Thread(target=_worker, args=(url, corpus, stop_at, warm_until, out))
          for _ in range(clients)]
    [t.start() for t in ts]; [t.join() for t in ts]
    q.put((tag, port, sorted(out)))


def _stats(out):
    if not out:
        return float("nan"), float("nan"), 0
    return sum(out) / len(out), out[int(0.95 * (len(out) - 1))], len(out)


def run_level(ports, k, probe_clients, bg_clients, corpus, duration, warmup):
    q = mp.Queue()
    start = time.time() + 5                      # lead time for process spawn on Windows
    stop_at, warm_until = start + duration, start + warmup
    procs = [mp.Process(target=_pod_proc,
                        args=("probe", ports[0], probe_clients, corpus, stop_at, warm_until, q))]
    for p in ports[1:1 + k]:
        procs.append(mp.Process(target=_pod_proc,
                                args=("bg", p, bg_clients, corpus, stop_at, warm_until, q)))
    [p.start() for p in procs]
    res = [q.get() for _ in procs]               # drain the queue before join
    [p.join() for p in procs]

    probe = next(r for r in res if r[0] == "probe")[2]
    bg = [_stats(r[2])[0] for r in res if r[0] == "bg"]
    pm, pp, pc = _stats(probe)
    return {"k": k, "D_node": k + 1, "probe_n": probe_clients - 1,
            "probe_mean_s": pm, "probe_p95_s": pp, "probe_count": pc,
            "probe_rps": pc / (duration - warmup),
            "bg_mean_s": (sum(bg) / len(bg)) if bg else float("nan"),
            "bg_clients": bg_clients}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ports", type=int, nargs="+", default=[8081, 8082, 8083, 8084, 8085])
    ap.add_argument("--levels", type=int, nargs="+", default=[0, 1, 2, 3, 4, 0])
    ap.add_argument("--probe-clients", type=int, default=1)
    ap.add_argument("--bg-clients", type=int, default=4)
    ap.add_argument("--duration", type=int, default=60)
    ap.add_argument("--warmup", type=int, default=10)
    ap.add_argument("--corpus", default=os.path.join("data", "sms_sample.txt"))
    ap.add_argument("--out", default=os.path.join("results", "cross_pod.csv"))
    a = ap.parse_args()
    assert max(a.levels) <= len(a.ports) - 1, "level k needs k background ports"

    corpus = [l.strip() for l in open(a.corpus, encoding="utf-8") if l.strip()]
    for p in a.ports:                            # warm every pod
        for _ in range(20):
            requests.post(f"http://localhost:{p}/classify", json={"text": corpus[0]}, timeout=30)

    rows, base = [], None
    for k in a.levels:
        r = run_level(a.ports, k, a.probe_clients, a.bg_clients, corpus, a.duration, a.warmup)
        base = base or r["probe_mean_s"]         # first level = reference
        r["ratio_vs_first"] = r["probe_mean_s"] / base
        rows.append(r)
        print(f"k={k} D_node={k+1} probe mean={r['probe_mean_s']*1000:7.1f} ms "
              f"p95={r['probe_p95_s']*1000:7.1f} ms ratio={r['ratio_vs_first']:.3f} "
              f"bg_mean={r['bg_mean_s']*1000:7.1f} ms")

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)


if __name__ == "__main__":
    mp.freeze_support()
    main()