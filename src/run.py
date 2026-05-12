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


# ── CPU utilization (real measurement) ───────────────────────────────────────

def _read_cpu_times():
    """Read total and idle CPU ticks from /proc/stat."""
    try:
        line = Path("/proc/stat").read_text().splitlines()[0]
        fields = list(map(int, line.split()[1:]))
        idle  = fields[3]
        total = sum(fields)
        return total, idle
    except Exception:
        return None, None


class CpuMonitor:
    """
    Measures average CPU utilization over a window by sampling /proc/stat
    at start and end. Returns utilization as a fraction 0.0–1.0.
    """
    def __init__(self):
        self._t0 = None
        self._i0 = None

    def start(self):
        self._t0, self._i0 = _read_cpu_times()

    def stop(self):
        t1, i1 = _read_cpu_times()
        if None in (self._t0, t1):
            return 0.0
        dt = t1 - self._t0
        di = i1 - self._i0
        if dt == 0:
            return 0.0
        return round(1.0 - di / dt, 4)


# ── GCE machine TDP table ─────────────────────────────────────────────────────
# Socket-level TDP for each GCE machine family used in this platform.
# Source: Google Cloud machine type specs + Intel/AMD ARK.
GCE_TDP_WATTS = {
    "e2-small":        15,
    "e2-medium":       30,
    "e2-standard-2":   50,
    "e2-standard-4":   80,
    "e2-standard-8":   120,
    "e2-standard-16":  180,
    "e2-highcpu-8":    100,
    "t2a-standard-2":  40,
    "t2a-standard-4":  60,
    "t2a-standard-8":  90,
    "n1-standard-4":   100,
}

def get_vm_tdp(machine_type: str) -> int:
    """Return TDP in watts for the given GCE machine type."""
    return GCE_TDP_WATTS.get(machine_type, 80)  # default 80W if unknown


def get_machine_type() -> str:
    """Read the GCE machine type from instance metadata."""
    try:
        import urllib.request
        req = urllib.request.Request(
            "http://metadata.google.internal/computeMetadata/v1/instance/machine-type",
            headers={"Metadata-Flavor": "Google"}
        )
        with urllib.request.urlopen(req, timeout=2) as r:
            # returns "projects/123/machineTypes/e2-standard-4"
            return r.read().decode().split("/")[-1]
    except Exception:
        return "unknown"


# ── Energy calculation ────────────────────────────────────────────────────────

def calculate_energy(cpu_utilization: float, tdp_watts: int, duration_sec: float) -> dict:
    """
    Energy = average power × time
    Average power = idle power + (utilization × (TDP - idle power))
    Idle power assumed to be 30% of TDP (typical server idle).
    """
    idle_fraction  = 0.30
    idle_watts     = tdp_watts * idle_fraction
    active_watts   = tdp_watts - idle_watts
    avg_power_w    = idle_watts + cpu_utilization * active_watts
    energy_wh      = round(avg_power_w * (duration_sec / 3600), 6)
    energy_j       = round(avg_power_w * duration_sec, 4)

    return {
        "machine_type":        get_machine_type(),
        "vm_tdp_watts":        tdp_watts,
        "cpu_utilization_pct": round(cpu_utilization * 100, 2),
        "avg_power_watts":     round(avg_power_w, 2),
        "duration_sec":        round(duration_sec, 4),
        "energy_wh":           energy_wh,
        "energy_joules":       energy_j,
    }


# ── System info ───────────────────────────────────────────────────────────────

def collect_system_info():
    cpu_count_logical = os.cpu_count() or 0
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

    try:
        meminfo = Path("/proc/meminfo").read_text()
        def _kb(key):
            for line in meminfo.splitlines():
                if line.startswith(key):
                    return int(line.split()[1])
            return 0
        ram_total_gb = round(_kb("MemTotal:")     / 1024 / 1024, 2)
        ram_avail_gb = round(_kb("MemAvailable:") / 1024 / 1024, 2)
        ram_used_gb  = round(ram_total_gb - ram_avail_gb, 2)
    except Exception:
        ram_total_gb = ram_avail_gb = ram_used_gb = 0

    try:
        st = os.statvfs("/")
        disk_total_gb = round(st.f_blocks * st.f_frsize / 1024**3, 2)
        disk_free_gb  = round(st.f_bavail * st.f_frsize / 1024**3, 2)
        disk_used_gb  = round(disk_total_gb - disk_free_gb, 2)
    except Exception:
        disk_total_gb = disk_free_gb = disk_used_gb = 0

    return {
        "cpu_model":            cpu_model,
        "cpu_logical_cores":    cpu_count_logical,
        "cpu_physical_cores":   physical_cores,
        "ram_total_gb":         ram_total_gb,
        "ram_used_gb":          ram_used_gb,
        "ram_available_gb":     ram_avail_gb,
        "disk_total_gb":        disk_total_gb,
        "disk_used_gb":         disk_used_gb,
        "disk_free_gb":         disk_free_gb,
        "hostname":             platform.node(),
        "python":               sys.version.split()[0],
        "os":                   platform.platform(),
    }


# ── HTML report ───────────────────────────────────────────────────────────────

def render_html(system, timing, energy, data_files, mode):
    def rows(d):
        return "".join(
            f"<tr><td>{k}</td><td><code>{v}</code></td></tr>"
            for k, v in d.items()
        )

    phase_bars = ""
    total = timing["total_sec"] or 1
    colours = ["#6366f1", "#0ea5e9", "#10b981", "#f59e0b", "#ef4444"]
    for i, (phase, secs) in enumerate(timing["phases"].items()):
        pct = round(secs / total * 100, 1)
        col = colours[i % len(colours)]
        phase_bars += f"""
        <tr>
          <td style="width:160px;padding:6px 12px 6px 0;font-size:13px">{phase}</td>
          <td style="padding:6px 0">
            <div style="background:#f3f4f6;border-radius:4px;overflow:hidden;height:20px;width:100%">
              <div style="background:{col};width:{max(pct,2)}%;height:100%;
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

    badge_color      = "#d1fae5" if mode == "success" else "#fee2e2"
    badge_text_color = "#065f46" if mode == "success" else "#991b1b"
    badge_label      = "✓ success" if mode == "success" else "✗ failed"

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
    .energy-box{{background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;
                 padding:16px 20px;margin-top:12px;display:grid;
                 grid-template-columns:1fr 1fr 1fr;gap:12px}}
    .energy-stat{{text-align:center}}
    .energy-stat .val{{font-size:22px;font-weight:600;color:#065f46}}
    .energy-stat .lbl{{font-size:12px;color:#6b7280;margin-top:2px}}
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

  <h2>Energy consumption</h2>
  <div class="energy-box">
    <div class="energy-stat">
      <div class="val">{energy['energy_wh']} Wh</div>
      <div class="lbl">Energy consumed</div>
    </div>
    <div class="energy-stat">
      <div class="val">{energy['avg_power_watts']} W</div>
      <div class="lbl">Avg power draw</div>
    </div>
    <div class="energy-stat">
      <div class="val">{energy['cpu_utilization_pct']}%</div>
      <div class="lbl">CPU utilization</div>
    </div>
  </div>
  <table style="margin-top:12px"><tbody>{rows(energy)}</tbody></table>

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
    p.add_argument("--mode",  choices=["success", "fail"], default="success")
    p.add_argument("--delay", type=int, default=0)
    return p.parse_args()


def main():
    args       = parse_args()
    timer      = Timer()
    cpu_mon    = CpuMonitor()
    start      = datetime.now(timezone.utc)

    print(f"[{start.isoformat()}] testbench starting — mode={args.mode} delay={args.delay}s")

    # Start CPU monitoring for the entire job
    cpu_mon.start()

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

    # ── Stop CPU monitor + calculate energy ────────────────────────────────────
    cpu_utilization = cpu_mon.stop()
    machine_type    = get_machine_type()
    tdp             = get_vm_tdp(machine_type)
    energy          = calculate_energy(cpu_utilization, tdp, timer.total())

    print(f"  CPU utilization : {energy['cpu_utilization_pct']}%")
    print(f"  Avg power       : {energy['avg_power_watts']} W")
    print(f"  Energy          : {energy['energy_wh']} Wh / {energy['energy_joules']} J")

    # ── Phase 4: write results ─────────────────────────────────────────────────
    timer.start("write_results")
    out = Path("/app/reports/results")
    out.mkdir(parents=True, exist_ok=True)

    end    = datetime.now(timezone.utc)
    timing = {
        "total_sec":   timer.total(),
        "phases":      timer.phases(),
        "started_at":  start.isoformat(),
        "finished_at": end.isoformat(),
    }

    metrics = {
        "status":     "success",
        "mode":       args.mode,
        "energy":     energy,
        "timing":     timing,
        "system":     system,
        "data_files": len(data_files),
        "data_paths": data_files[:50],
    }

    (out / "metrics.json").write_text(json.dumps(metrics, indent=2))
    (out / "report.html").write_text(
        render_html(system, timing, energy, data_files, args.mode)
    )
    timer.stop()

    print(f"  Results written in {timer.phases()['write_results']}s")
    print(f"[DONE] total={timer.total()}s")


if __name__ == "__main__":
    main()
