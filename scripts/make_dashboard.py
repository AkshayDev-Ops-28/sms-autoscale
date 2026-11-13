"""Generates k8s/dashboard.json (Grafana dashboard) -- run by run.ps1."""
import json
from pathlib import Path

DS = {"type": "prometheus", "uid": "prometheus"}
POD = 'namespace="default",pod=~"sms-spam-.*",container="sms-spam"'


def panel(pid, title, targets, unit, x, y, w=12, h=8, desc=""):
    return {
        "id": pid, "type": "timeseries", "title": title, "description": desc, "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "fieldConfig": {"defaults": {"unit": unit, "custom": {"lineWidth": 2, "fillOpacity": 8}}, "overrides": []},
        "targets": [{"refId": chr(65 + i), "expr": e, "legendFormat": l, "datasource": DS}
                    for i, (e, l) in enumerate(targets)],
    }


panels = [
    panel(1, "Pods: ready vs desired replicas", [
        ('kube_deployment_status_replicas_ready{deployment="sms-spam"}', "ready pods"),
        ('kube_horizontalpodautoscaler_status_desired_replicas{horizontalpodautoscaler="keda-hpa-sms-spam-scaler"}', "desired (KEDA/HPA)"),
    ], "short", 0, 0),
    panel(2, "Traffic: actual vs forecast (aligned to the time it predicts)", [
        ("sum(rate(sms_requests_total[20s]))", "actual req/s"),
        ("max(predicted_rps) offset 45s", "forecast made 45s earlier"),
        ("max(predicted_rps)", "forecast for t+45s (live)"),
    ], "reqps", 12, 0, desc="Offset must equal HORIZON_S in k8s/forecaster.yaml"),
    panel(3, "CPU per pod (cores)", [
        (f"sum by (pod) (rate(container_cpu_usage_seconds_total{{{POD}}}[30s]))", "{{pod}}"),
    ], "short", 0, 8),
    panel(4, "Memory per pod", [
        (f"sum by (pod) (container_memory_working_set_bytes{{{POD}}})", "{{pod}}"),
    ], "bytes", 12, 8),
    panel(5, "p95 latency", [
        ("histogram_quantile(0.95, sum by (le) (rate(sms_request_seconds_bucket[30s])))", "p95"),
    ], "s", 0, 16),
    panel(6, "Deadline-miss ratio", [
        ('sum(rate(sms_deadline_total{outcome="missed"}[30s])) / sum(rate(sms_deadline_total[30s]))', "missed / total"),
    ], "percentunit", 12, 16),
    panel(7, "Forecast quality: mean abs error (req/s)", [
        ("max(forecast_abs_error_rps)", "MAE"),
        ("max(forecast_model_ready)", "model in use (1) / fallback (0)"),
    ], "short", 0, 24, w=24, h=6),
]

dash = {
    "uid": "sms-autoscale", "title": "Predictive autoscaling - SMS spam", "schemaVersion": 39,
    "version": 1, "refresh": "5s", "time": {"from": "now-15m", "to": "now"},
    "tags": ["autoscaling"], "panels": panels,
}
out = Path(__file__).resolve().parent.parent / "k8s" / "dashboard.json"
out.write_text(json.dumps(dash, indent=1))
print("wrote", out)
