#!/usr/bin/env python3
"""
Platform testbench script.

Modes:
  --mode success  (default) reads data, runs phases, writes results
  --mode fail     raises an intentional error to test error reporting

Optional:
  --delay N       add N seconds of fake computation to simulate a longer job
"""
import argparse
import json
import os
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


# ── Timing ────────────────────────────────────────────────────────────────────

class Timer:
    def __init__(self):
        self._phases = {}
        self._start = None

    def start(self, name):
        self._start = (name, time.perf_counter())

    def stop(self):
        name, t0 = self._start
        self._phases[name] = round(time.perf_counter() - t0, 4)
        self._start = None

    def phases(self):
        return self._phases

    def total(self):
        return round(sum(self._phases.values()), 4)


# ── System info ───────────────────────────────────────────────────────────────

def collect_system_info():
    # CPU
    cpu_count_logical = os.cpu_count() or 0

    # Try to get physical cores from /proc/cpuinfo (Linux only)
    try:
        cpuinfo = Path("/proc/cpuinfo").read_text()
        physical_cores = len(set(
            line.split(":")[1].strip()
            for line in cpuinfo.splitlines()
            if line.startswith("physical id")
        )) or cpu_count_logical
        cpu_model = next(
            (line.split(":")[1].strip()
             for line in cpuinfo.splitlines()
             if line.startswith("model name")),
            "unknown"
        )
    except Exception:
        physical_cores = cpu_count_logical
        cpu_model = platform.processor() or "unknown"

    # RAM from /proc/meminfo
    try:
        meminfo = Path("/proc/meminfo").read_text()
        def _kb(key):
            for line in meminfo.splitlines():
                if line.startswith(key):
                    return int(line.split()[1])
            return 0
        ram_total_gb = round(_kb("MemTotal:") / 1024 / 1024, 2)
        ram_avail_gb = round(_kb("MemAvailable:") / 1024 / 1024, 2)
        ram_used_gb  = round(ram_total_gb - ram_avail_gb, 2)
    except Exception:
        ram_total_gb = ram_avail_gb = ram_used_gb = 0

    # Disk usage of /workspace
    try:
        st = os.statvfs("/")
        disk_total_gb = round(st.f_blocks * st.f_frsize / 1024**3, 2)
        disk_free_gb  = round(st.f_bavail * st.f_frsize / 1024**3, 2)
        disk_used_gb  = round(disk_total_gb - disk_free_gb, 2)
    except Exception:
        disk_total_gb = disk_free_gb = disk_used_gb = 0

    return {
        "cpu_model":        cpu_model,
        "cpu_logical_cores": cpu_count_logical,
        "cpu_physical_cores": physical_cores,
        "ram_total_gb":     ram_total_gb,
        "ram_used_gb":      ram_used_gb,
        "ram_available_gb": ram_avail_gb,
        "disk_total_gb":    disk_total_gb,
        "disk_used_gb":     disk_used_gb,
        "disk_free_gb":     disk_free_gb,
        "hostname":         platform.node(),
        "python":           sys.version.split()[0],
        "os":               platform.platform(),
    }


# ── HTML report ───────────────────────────────────────────────────────────────

def render_html(system, timing, data_files, mode):
    def rows(d):
        return "".join(
            f"<tr><td>{k}</td><td><code>{v}</code></td></tr>"
            for k, v in d.items()
        )

    phase_bars = ""
    total = timing["total_sec"] or 1
    colours = ["#6366f1","#0ea5e9","#10b981","#f59e0b","#ef4444"]
    for i, (phase, secs) in enumerate(timing["phases"].items()):
        pct = round(secs / total * 100, 1)
        col = colours[i % len(colours)]
        phase_bars += f"""
        <tr>
          <td style="width:160px;padding:6px 12px 6px 0;font-size:13px">{phase}</td>
          <td style="padding:6px 0">
            <div style="background:#f3f4f6;border-radius:4px;overflow:hidden;height:20px;width:100%">
              <div style="background:{col};width:{pct}%;height:100%;
                          display:flex;align-items:center;padding-left:8px;
                          font-size:11px;color:#fff;white-space:nowrap">
                {secs}s ({pct}%)
              </div>
            </div>
          </td>
        </tr>"""

    file_list = "\n".join(
        f'<li style="font-size:13px;font-family:monospace">{f}</li>'
        for f in data_files
    ) or "<li style='color:#9ca3af'>no files found</li>"

    badge_color = "#d1fae5" if mode == "success" else "#fee2e2"
    badge_text_color = "#065f46" if mode == "success" else "#991b1b"
    badge_label = "✓ success" if mode == "success" else "✗ failed"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Testbench report</title>
  <style>
    body{{font-family:system-ui,sans-serif;max-width:820px;margin:48px auto;
         padding:0 24px;color:#111;line-height:1.6}}
    h1{{font-size:22px;font-weight:500;margin-bottom:4px}}
    h2{{font-size:15px;font-weight:500;margin-top:36px;margin-bottom:12px;
        border-bottom:1px solid #e5e7eb;padding-bottom:6px}}
    .badge{{display:inline-block;padding:3px 12px;border-radius:99px;font-size:13px;
            font-weight:500;background:{badge_color};color:{badge_text_color};margin-left:8px}}
    table{{width:100%;border-collapse:collapse;font-size:14px}}
    td,th{{text-align:left;padding:8px 12px;border-bottom:1px solid #f3f4f6}}
    th{{background:#f9fafb;font-weight:500;font-size:13px}}
    td:first-child{{color:#6b7280;width:220px}}
    ul{{margin:0;padding-left:20px}}
    .total{{font-size:13px;color:#6b7280;margin-top:8px}}
  </style>
</head>
<body>
  <h1>Testbench report <span class="badge">{badge_label}</span></h1>

  <h2>System info</h2>
  <table><tbody>{rows(system)}</tbody></table>

  <h2>Timing breakdown</h2>
  <table><tbody>{phase_bars}</tbody></table>
  <p class="total">Total: {timing['total_sec']}s</p>

  <h2>Data files ({len(data_files)})</h2>
  <ul>{file_list}</ul>
</body>
</html>"""


# ── Main ──────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["success", "fail"], default="success")
    p.add_argument("--delay", type=int, default=0)
    return p.parse_args()


def main():
    args  = parse_args()
    timer = Timer()
    start = datetime.now(timezone.utc)

    print(f"[{start.isoformat()}] testbench starting — mode={args.mode} delay={args.delay}s")

    # ── Phase 1: system info ───────────────────────────────────────────────────
    timer.start("system_info")
    system = collect_system_info()
    timer.stop()

    print(f"  CPU : {system['cpu_model']} ({system['cpu_logical_cores']} logical cores)")
    print(f"  RAM : {system['ram_used_gb']} / {system['ram_total_gb']} GB used")
    print(f"  Disk: {system['disk_used_gb']} / {system['disk_total_gb']} GB used")

    # ── Phase 2: data load ─────────────────────────────────────────────────────
    timer.start("data_load")
    data_dir   = Path("/app/data")
    all_files  = sorted(data_dir.rglob("*")) if data_dir.exists() else []
    data_files = [str(f.relative_to(data_dir)) for f in all_files if f.is_file()]
    timer.stop()

    print(f"  Data: {len(data_files)} file(s) in /app/data/")

    # ── Phase 3: computation (simulated) ──────────────────────────────────────
    timer.start("computation")
    if args.delay:
        print(f"  Sleeping {args.delay}s to simulate computation…")
        time.sleep(args.delay)
    timer.stop()

    # ── Intentional failure ────────────────────────────────────────────────────
    if args.mode == "fail":
        raise RuntimeError(
            "Intentional failure — if you see this in the UI, error reporting works."
        )

    # ── Phase 4: write results ─────────────────────────────────────────────────
    timer.start("write_results")
    out = Path("/app/reports/results")
    out.mkdir(parents=True, exist_ok=True)

    end     = datetime.now(timezone.utc)
    timing  = {
        "total_sec": timer.total(),
        "phases":    timer.phases(),
        "started_at":  start.isoformat(),
        "finished_at": end.isoformat(),
    }

    metrics = {
        "status":     "success",
        "mode":       args.mode,
        "timing":     timing,
        "system":     system,
        "data_files": len(data_files),
        "data_paths": data_files[:50],
    }

    (out / "metrics.json").write_text(json.dumps(metrics, indent=2))
    (out / "report.html").write_text(render_html(system, timing, data_files, args.mode))
    timer.stop()

    print(f"  Results written in {timer.phases()['write_results']}s")
    print(f"[DONE] total={timer.total()}s")


if __name__ == "__main__":
    main()
