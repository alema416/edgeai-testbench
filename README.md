# job-runner-test

Minimal test repo for the job runner platform.

## What it tests

| Feature | How |
|---|---|
| git clone | this repo |
| GCS data pull | lists every file found under `/app/data/` |
| Docker build | uses platform template Dockerfile (no Dockerfile here) |
| Entrypoint | `src/run.py` |
| Args | `--mode` and `--delay` |
| Results push | writes `reports/results/metrics.json` + `report.html` |
| HTML preview | `report.html` opens in browser via UI |
| Error reporting | `--mode fail` raises an intentional exception |

## Submit via UI

| Field | Value |
|---|---|
| Repo URL | `https://github.com/YOUR_ORG/job-runner-test` |
| Project name | your GCS data folder name |
| Entrypoint | `src/run.py` |
| Args (success) | *(leave empty)* |
| Args (failure) | `--mode fail` |
| Args (slow) | `--delay 30` |
