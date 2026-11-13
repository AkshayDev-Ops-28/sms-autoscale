# Usage:  .\run.ps1 setup                  (once, before presenting)
#         .\run.ps1 up                     (start of the presentation)
#         .\run.ps1 mode reactive|predictive
#         .\run.ps1 status | down
param([string]$Cmd = "help", [string]$Arg = "")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Publish-Dashboard {
  python scripts/make_dashboard.py
  kubectl create configmap sms-dashboard -n monitoring --from-file=sms-autoscaling.json=k8s/dashboard.json --dry-run=client -o yaml | kubectl apply -f -
  kubectl label configmap sms-dashboard -n monitoring grafana_dashboard=1 --overwrite
}
function Publish-Locust {
  kubectl create configmap locust-files --from-file=locustfile.py=loadgen/locustfile.py --from-file=sms_sample.txt=data/sms_sample.txt --dry-run=client -o yaml | kubectl apply -f -
  kubectl apply -f k8s/locust.yaml
}

switch ($Cmd) {
  "setup" {
    $cpus = if ($env:MK_CPUS) { $env:MK_CPUS } else { 4 }
    $mem  = if ($env:MK_MEM)  { $env:MK_MEM }  else { 7168 }
    python -m pip install huggingface_hub
    python scripts/fetch_assets.py
    minikube start --driver=docker --cpus=$cpus --memory=$mem --disk-size=15g
    helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
    helm repo add kedacore https://kedacore.github.io/charts
    helm repo update
    helm upgrade --install prom prometheus-community/kube-prometheus-stack -n monitoring --create-namespace -f k8s/monitoring-values.yaml --wait --timeout 10m
    helm upgrade --install keda kedacore/keda -n keda --create-namespace --wait
    & minikube -p minikube docker-env --shell powershell | Invoke-Expression   # build INSIDE minikube
    docker build -f app/Dockerfile -t sms-spam:v1 .
    docker build -f forecaster/Dockerfile -t sms-forecaster:v1 .
    kubectl apply -f k8s/app.yaml
    kubectl apply -f k8s/forecaster.yaml
    Publish-Dashboard
    Publish-Locust
    kubectl rollout status deploy/sms-spam --timeout=300s
    Write-Host "Setup complete. Next: .\run.ps1 up"
  }
  "up" {
    minikube start
    kubectl rollout status deploy/sms-spam --timeout=300s
    Get-Process kubectl -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Process kubectl -WindowStyle Hidden -ArgumentList "port-forward -n monitoring svc/grafana 3000:80"
    Start-Process kubectl -WindowStyle Hidden -ArgumentList "port-forward svc/locust 8089:8089"
    Start-Process kubectl -WindowStyle Hidden -ArgumentList "port-forward -n monitoring svc/prom-prometheus 9090:9090"
    Write-Host "Grafana  http://localhost:3000  (admin / admin) -> dashboard 'Predictive autoscaling - SMS spam'"
    Write-Host "Locust   http://localhost:8089"
    Write-Host "Next: .\run.ps1 mode reactive"
  }
  "mode" {
    if ($Arg -notin "reactive", "predictive") { throw "usage: .\run.ps1 mode reactive|predictive" }
    kubectl delete scaledobject sms-spam-scaler --ignore-not-found
    kubectl scale deploy/sms-spam --replicas=1
    kubectl rollout status deploy/sms-spam --timeout=120s
    kubectl apply -f "k8s/scaledobject-$Arg.yaml"
    Write-Host "Mode = $Arg. Open http://localhost:8089 and press Start."
  }
  "status" { kubectl get pods, scaledobject, hpa }
  "down" {
    Get-Process kubectl -ErrorAction SilentlyContinue | Stop-Process -Force
    minikube stop
  }
  default { Get-Content $PSCommandPath -TotalCount 5 }
}
