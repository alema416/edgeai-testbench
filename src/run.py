#!/usr/bin/env python3
"""
Platform test script.

Modes:
  --mode success  (default) reads data, writes results, exits 0
  --mode fail     raises an intentional error to test error reporting

Optional:
  --delay N       sleep N seconds to simulate a longer job
"""
import argparse
import json
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["success", "fail"], default="success")
    p.add_argument("--delay", type=int, default=0)
    return p.parse_args()


def main():
    args = parse_args()
    start = datetime.now(timezone.utc)

    print(f"[{start.isoformat()}] test job starting")
    print(f"  mode    : {args.mode}")
    print(f"  delay   : {args.delay}s")
    print(f"  python  : {sys.version.split()[0]}")
    print(f"  host    : {platform.node()}")

    # ── 1. Read data directory (confirms GCS pull worked) ─────────────────────
    data_dir = Path("/app/data")
    all_files = sorted(data_dir.rglob("*")) if data_dir.exists() else []
    files = [f for f in all_files if f.is_file()]

    print(f"\n[DATA] {len(files)} file(s) in /app/data/")
    for f in files[:10]:
        print(f"  {f.relative_to(data_dir)}  ({f.stat().st_size:,} B)")
    if len(files) > 10:
        print(f"  … and {len(files) - 10} more")

    # ── 2. Simulate work ───────────────────────────────────────────────────────
    if args.delay:
        print(f"\n[WORK] sleeping {args.delay}s …")
        time.sleep(args.delay)

    # ── 3. Intentional failure (tests error path end-to-end) ──────────────────
    if args.mode == "fail":
        raise RuntimeError(
            "Intentional failure — if you can read this in the UI, error reporting works."
        )

    # ── 4. Write results ───────────────────────────────────────────────────────
    end = datetime.now(timezone.utc)
    duration = round((end - start).total_seconds(), 2)

    out = Path("/app/reports/results")
    out.mkdir(parents=True, exist_ok=True)

    metrics = {
        "status":       "success",
        "mode":         args.mode,
        "duration_sec": duration,
        "started_at":   start.isoformat(),
        "finished_at":  end.isoformat(),
        "host":         platform.node(),
        "python":       sys.version.split()[0],
        "data_files":   len(files),
        "data_paths":   [str(f.relative_to(data_dir)) for f in files[:50]],
    }

    # JSON — downloadable KPI file
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2))

    # HTML — previewable report
    rows = "".join(
        f"<tr><td>{k}</td><td><code>{v}</code></td></tr>"
        for k, v in metrics.items()
        if not isinstance(v, list)
    )
    file_list = "\n".join(
        str(f.relative_to(data_dir)) for f in files
    ) or "(no files found)"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Test report</title>
  <style>
    body{{font-family:system-ui,sans-serif;max-width:760px;margin:48px auto;padding:0 20px;color:#111}}
    h1{{font-size:22px;font-weight:500;margin-bottom:4px}}
    .ok{{display:inline-block;background:#d1fae5;color:#065f46;border-radius:99px;
         padding:2px 10px;font-size:13px;font-weight:500;margin-left:8px}}
    table{{width:100%;border-collapse:collapse;margin-top:24px;font-size:14px}}
    th,td{{text-align:left;padding:9px 12px;border-bottom:1px solid #e5e7eb}}
    th{{background:#f9fafb;font-weight:500}}
    pre{{background:#f3f4f6;padding:16px;border-radius:8px;font-size:13px;
         overflow-x:auto;white-space:pre-wrap}}
    h2{{font-size:16px;font-weight:500;margin-top:32px}}
  </style>
</head>
<body>
  <h1>Job runner test <span class="ok">✓ success</span></h1>
  <table>
    <tr><th>Field</th><th>Value</th></tr>
    {rows}
  </table>
  <h2>Data files ({len(files)})</h2>
  <pre>{file_list}</pre>
  <h2>Raw metrics</h2>
  <pre>{json.dumps(metrics, indent=2)}</pre>
</body>
</html>"""

    (out / "report.html").write_text(html)

    print(f"\n[OK] done in {duration}s")
    print(f"     metrics.json → reports/results/metrics.json")
    print(f"     report.html  → reports/results/report.html")


if __name__ == "__main__":
    main()
