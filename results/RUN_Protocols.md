# Run protocol (identical for reactive and predictive)

## Once per PowerShell window
Set-ExecutionPolicy -Scope Process Bypass

## Before each run
1. `.\run.ps1 up`            (starts hidden port-forwards; run it FIRST, it kills all kubectl processes)
2. `.\run.ps1 mode <reactive|predictive>`
3. `.\run.ps1 status`        -> 1 sms-spam pod Running, forecaster Running, HPA at 1 replica
4. Open Grafana, check the dashboard loads; open Locust, make sure no test is running
5. New window: start the timestamped HPA log (below) -> results\<mode>_run<N>\hpa_log.txt
6. Note run ID and start time in results\<mode>_run<N>\notes.txt

## Run
7. Locust: Start. Set Run time to 600s if the form has it (1 warm-up cycle + 3 measured cycles)
8. At the 150 s mark, press Reset Stats (discards the warm-up cycle)
9. Do NOT stop early. Let all 4 cycles finish.

## After the run
10. Locust: Download Data -> save stats, history and failures CSVs to results\<mode>_run<N>\
11. Grafana screenshots (pods, traffic) named <mode>_run<N>_pods.png etc.
12. Leave the HPA log running 3-5 min until replicas return to 1, then stop it (Ctrl+C)
13. Record the replica-return time in notes.txt



#keep the threshold flexible acc to traffic and set acc to deadline