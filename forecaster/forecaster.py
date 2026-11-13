"""Predictive autoscaling forecaster.

Every STEP_S seconds it:
  1. pulls recent request-rate history from Prometheus,
  2. (re)fits a ridge-regression autoregressive model on that history,
  3. predicts the request rate HORIZON_S seconds ahead,
  4. publishes it as the Prometheus gauge `predicted_rps`, which KEDA reads.

Features: the last LAGS samples (captures level + trend) and, optionally, the
value one season (SEASON_S) before the target time (captures repeating load).
Falls back to "last observed value" until there is enough history.
"""
import logging
import os
import time
from collections import deque

import numpy as np
import requests
from prometheus_client import Gauge, start_http_server

PROM = os.getenv("PROM_URL", "http://prom-prometheus.monitoring.svc:9090")
QUERY = os.getenv("QUERY", "sum(rate(sms_requests_total[20s]))")
STEP_S = int(os.getenv("STEP_S", "5"))
HORIZON_S = int(os.getenv("HORIZON_S", "45"))   # >= pod start-up time (image + model load)
LAGS = int(os.getenv("LAGS", "12"))
SEASON_S = int(os.getenv("SEASON_S", "0"))      # 0 = no seasonal feature
HISTORY_S = int(os.getenv("HISTORY_S", "1800"))
RIDGE = float(os.getenv("RIDGE", "1.0"))
MIN_ROWS = int(os.getenv("MIN_ROWS", "20"))

PRED = Gauge("predicted_rps", "Forecast request rate HORIZON_S seconds ahead")
ACTUAL = Gauge("forecast_current_rps", "Latest observed request rate")
MAE = Gauge("forecast_abs_error_rps", "Mean absolute error of recent forecasts")
READY = Gauge("forecast_model_ready", "1 if the regression model is in use, 0 if persistence fallback")


def features(y, i, L, h, P):
    f = [1.0] + [y[i - k] for k in range(L)]
    if P:
        f.append(y[i + h - P])
    return f


def forecast(y, step_s=STEP_S, horizon_s=HORIZON_S, lags=LAGS, season_s=SEASON_S, ridge=RIDGE):
    """Return (prediction, model_used) for the value horizon_s after the last sample of y."""
    y = np.asarray(y, dtype=float)
    n = len(y)
    if n == 0:
        return 0.0, False
    h = max(1, round(horizon_s / step_s))
    P = round(season_s / step_s) if season_s else 0
    if P and P <= h:
        P = 0
    first = max(lags - 1, (P - h) if P else 0)
    last = n - 1 - h
    if last - first + 1 < MIN_ROWS:
        return float(y[-1]), False
    X = np.array([features(y, i, lags, h, P) for i in range(first, last + 1)])
    t = np.array([y[i + h] for i in range(first, last + 1)])
    reg = ridge * np.eye(X.shape[1])
    reg[0, 0] = 0.0  # don't penalise the intercept
    w = np.linalg.solve(X.T @ X + reg, X.T @ t)
    pred = float(np.array(features(y, n - 1, lags, h, P)) @ w)
    return float(min(max(pred, 0.0), 2.0 * y.max() + 1.0)), True


def fetch_history():
    end = time.time()
    start = end - HISTORY_S
    r = requests.get(
        f"{PROM}/api/v1/query_range",
        params={"query": QUERY, "start": start, "end": end, "step": STEP_S},
        timeout=5,
    )
    r.raise_for_status()
    result = r.json()["data"]["result"]
    if not result:
        return np.array([]), np.array([])
    pts = {int(float(ts)): float(v) for ts, v in result[0]["values"]}
    grid = np.arange(min(pts), max(pts) + 1, STEP_S)
    vals, last = [], 0.0
    for ts in grid:  # forward-fill gaps, treat NaN as 0
        v = pts.get(int(ts), last)
        last = 0.0 if np.isnan(v) else v
        vals.append(last)
    return grid, np.array(vals)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    start_http_server(8000)
    pending = {}           # target_ts -> prediction
    errors = deque(maxlen=24)
    while True:
        t0 = time.time()
        try:
            ts, y = fetch_history()
            if len(y):
                pred, used = forecast(y)
                PRED.set(pred)
                ACTUAL.set(y[-1])
                READY.set(1 if used else 0)
                pending[int(ts[-1]) + HORIZON_S] = pred
                for tgt in [k for k in pending if k <= ts[-1]]:  # score forecasts whose time has come
                    idx = int(np.argmin(np.abs(ts - tgt)))
                    errors.append(abs(pending.pop(tgt) - y[idx]))
                if errors:
                    MAE.set(float(np.mean(errors)))
                logging.info("now=%.1f rps  predicted(+%ds)=%.1f rps  model=%s", y[-1], HORIZON_S, pred, used)
        except Exception as exc:  # keep running if Prometheus is briefly unavailable
            logging.warning("forecast loop error: %s", exc)
        time.sleep(max(0.0, STEP_S - (time.time() - t0)))


if __name__ == "__main__":
    main()
