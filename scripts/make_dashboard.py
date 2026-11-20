"""Generates k8s/dashboard.json (Grafana dashboard) -- run by run.ps1."""
import json
from pathlib import Path

DS = {"type": "prometheus", "uid": "prometheus"}
POD = 'namespace="default",pod=~"sms-spam-.*",container="sms-spam"'

# ---- calibrated model constants (keep in sync with scripts/estimator.py) ----
THRESHOLD = 6        # req/s per pod used by both ScaledObjects
MAX_PODS = 3         # maxReplicaCount
S0_S = 0.052         # idle single-request time, seconds
RR = 2.2             # slowdown per extra in-flight request on the same pod
BETA = 0.25          # slowdown per extra busy pod
P95_RATIO = 1.6      # measured p95 / mean
DEADLINE_S = 1.0     # normal-class deadline

READY = 'kube_deployment_status_replicas_ready{deployment="sms-spam"}'
LIVE_RATE = "sum(rate(sms_requests_total[20s]))"
# n = other in-flight requests per pod (avg in-flight minus the request itself)
# k = other busy pods = ready pods - 1
PRED_P95 = (
    f"{P95_RATIO}*{S0_S}"
    f"*(1+{RR}*clamp_min(avg(avg_over_time(sms_inflight_requests[20s]))-1,0))"
    f"*(1+{BETA}*clamp_min(max({READY})-1,0))"
)
OBS_P95 = "histogram_quantile(0.95, sum by (le) (rate(sms_request_seconds_bucket[30s])))"


def panel(pid, title, targets, unit, x, y, w=12, h=8, desc=""):
    return {
        "id": pid, "type": "timeseries", "title": title, "description": desc, "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "fieldConfig": {"defaults": {"unit": unit, "custom": {"lineWidth": 2, "fillOpacity": 8}}, "overrides": []},
        "targets": [{"refId": chr(65 + i), "expr": e, "legendFormat": l, "datasource": DS}
                    for i, (e, l) in enumerate(targets)],
    }


panels = [
    panel(1, "Pods: ready vs desired replicas vs model", [
        (READY, "ready pods"),
        ('kube_horizontalpodautoscaler_status_desired_replicas{horizontalpodautoscaler="keda-hpa-sms-spam-scaler"}', "desired (KEDA/HPA)"),
        (f"clamp_max(ceil({LIVE_RATE} / {THRESHOLD}), {MAX_PODS})", "pods the model needs (live rate)"),
    ], "short", 0, 0, desc=f"Model need = ceil(rate / {THRESHOLD} req/s per pod), capped at {MAX_PODS}"),
    panel(2, "Traffic: actual vs forecast (aligned to the time it predicts)", [
        (LIVE_RATE, "actual req/s"),
        ("max(predicted_rps offset 45s)", "forecast made 45s earlier"),
        ("max(predicted_rps)", "forecast for t+45s (live)"),
    ], "reqps", 12, 0, desc="Offset must equal HORIZON_S in k8s/forecaster.yaml"),
    panel(3, "CPU per pod (cores)", [
        (f"sum by (pod) (rate(container_cpu_usage_seconds_total{{{POD}}}[30s]))", "{{pod}}"),
    ], "short", 0, 8),
    panel(4, "Memory per pod", [
        (f"sum by (pod) (container_memory_working_set_bytes{{{POD}}})", "{{pod}}"),
    ], "bytes", 12, 8),
    panel(5, "p95 latency", [
        (OBS_P95, "p95"),
    ], "s", 0, 16),
    panel(6, "Deadline-miss ratio", [
        ('sum(rate(sms_deadline_total{outcome="missed"}[30s])) / sum(rate(sms_deadline_total[30s]))', "missed / total"),
    ], "percentunit", 12, 16),
    panel(7, "Forecast quality: mean abs error (req/s)", [
        ("max(forecast_abs_error_rps)", "MAE"),
        ("max(forecast_model_ready)", "model in use (1) / fallback (0)"),
    ], "short", 0, 24, w=24, h=6),
    panel(8, "Load vs model capacity", [
        (LIVE_RATE, "actual req/s"),
        (f"{THRESHOLD} * {READY}", f"capacity of ready pods ({THRESHOLD} req/s each)"),
        (f"{THRESHOLD * MAX_PODS}", f"max capacity ({MAX_PODS} pods)"),
    ], "reqps", 0, 30, desc="Load above the capacity line means the pods are behind; scaling should keep it below."),
    panel(9, "Model validation: predicted vs observed p95 latency", [
        (PRED_P95, "predicted p95 (model)"),
        (OBS_P95, "observed p95"),
        (f"vector({DEADLINE_S})", "deadline (1000 ms)"),
    ], "s", 12, 30,
        desc="S = 52ms x (1 + 2.2n) x (1 + 0.25k), p95 = 1.6 x mean; n from in-flight gauge, k = ready pods - 1"),
]

dash = {
    "uid": "sms-autoscale", "title": "Predictive autoscaling - SMS spam", "schemaVersion": 39,
    "version": 1, "refresh": "5s", "time": {"from": "now-15m", "to": "now"},
    "tags": ["autoscaling"], "panels": panels,
}
out = Path(__file__).resolve().parent.parent / "k8s" / "dashboard.json"
out.write_text(json.dumps(dash, indent=1))
print("wrote", out)