# Predictive autoscaling for an ML inference service (SMS spam DistilBERT)

Locust (wave traffic) -> sms-spam pods (FastAPI + DistilBERT) -> Prometheus -> KEDA -> scales pods
                                         ^ forecaster.py reads history, publishes `predicted_rps`

## One-time setup (before presenting, ~20-30 min, needs internet)
    .\run.ps1 setup          # env MK_CPUS / MK_MEM override minikube size (default 4 CPU / 7168 MB)

## Presenting from zero
| Step | Command | What to show |
|------|---------|--------------|
| 1 | `.\run.ps1 up` | cluster starts; Grafana :3000 (admin/admin), Locust :8089 |
| 2 | `.\run.ps1 mode reactive` | baseline autoscaler (live-rate trigger only) |
| 3 | Locust UI -> Start | pods, CPU/mem, latency, deadline-miss in Grafana |
| 4 | note the time window, then `.\run.ps1 mode predictive` | live + forecast triggers |
| 5 | Locust UI -> Start (same wave) | compare the two windows |
| end | `.\run.ps1 down` | |

Tip: for a shorter live demo set WAVE_CYCLES to 2 in k8s/locust.yaml, then `kubectl apply -f k8s/locust.yaml`.

## Knobs that must match
- `threshold: "20"` in both ScaledObjects = sustainable req/s of ONE pod. Calibrate it (see notes) before the demo.
- `HORIZON_S` (forecaster.yaml) ~ pod start-up time; the dashboard's `offset 45s` must equal it.
- `SEASON_S` (forecaster.yaml) = `WAVE_PERIOD` (locust.yaml).


