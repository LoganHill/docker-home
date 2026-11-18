#!/usr/bin/env python3
"""ZFS scrub and backup-unit state for node-exporter's textfile collector.

Run every few minutes by host-metrics.timer. Usage: host-metrics.py [out_dir] [unit...]
"""
import json
import os
import re
import subprocess
import sys

out_dir = sys.argv[1] if len(sys.argv) > 1 else "/srv/monitoring/textfile"
units = sys.argv[2:] or ["restic-backup.service"]
out = os.path.join(out_dir, "host.prom")
metrics = {}  # name -> (help, [(labels, value)])


def add(name, help_, labels, value):
    metrics.setdefault(name, (help_, []))[1].append((labels, value))


def run(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout


def previous(name, labels):
    """Value of a series from the last run, so it survives a reboot or a failed run."""
    try:
        with open(out) as f:
            m = re.search(rf"^{name}\{{{re.escape(labels)}\}} (\S+)$", f.read(), re.M)
            return m and m.group(1)
    except OSError:
        return None


# --- ZFS -------------------------------------------------------------------
try:
    pools = json.loads(run("zpool", "status", "-j", "--json-int"))["pools"]
    for name, pool in pools.items():
        lbl = f'pool="{name}"'
        scan = pool.get("scan_stats") or {}
        scrub = scan.get("function") == "SCRUB"
        add("zfs_pool_data_errors", "Permanent data errors reported by zpool status.", lbl, pool.get("error_count", 0))
        add("zfs_scrub_in_progress", "1 while a scrub is running.", lbl, int(scrub and scan.get("state") == "SCANNING"))
        last = scan.get("end_time") if scrub and scan.get("state") == "FINISHED" else previous("zfs_scrub_last_completed_timestamp_seconds", lbl)
        if last:
            add("zfs_scrub_last_completed_timestamp_seconds", "When the last completed scrub finished.", lbl, last)
            add("zfs_scrub_last_errors", "Errors found by the last scan.", lbl, scan.get("errors", 0))
except (subprocess.CalledProcessError, KeyError, ValueError) as e:
    print(f"zpool: {e}", file=sys.stderr)

# Pool capacity: node-exporter only sees per-dataset free space, and ZFS slows
# down well before a pool is full.
try:
    for line in run("zpool", "list", "-Hp", "-o", "name,size,alloc").splitlines():
        name, size, alloc = line.split("\t")
        add("zfs_pool_size_bytes", "Pool size (zpool list).", f'pool="{name}"', size)
        add("zfs_pool_allocated_bytes", "Pool space allocated (zpool list).", f'pool="{name}"', alloc)
except (subprocess.CalledProcessError, ValueError) as e:
    print(f"zpool list: {e}", file=sys.stderr)

# Newest sanoid snapshot per dataset (autosnap_* only: the transient @restic
# snapshot taken by the backup would otherwise look like a fresh one).
try:
    newest = {}
    for line in run("zfs", "list", "-Hp", "-t", "snapshot", "-o", "name,creation").splitlines():
        name, created = line.split("\t")
        dataset, snap = name.split("@", 1)
        if snap.startswith("autosnap_"):
            newest[dataset] = max(newest.get(dataset, 0), int(created))
    for dataset, created in newest.items():
        add("zfs_snapshot_newest_timestamp_seconds", "Creation time of the newest sanoid snapshot.",
            f'dataset="{dataset}"', created)
except (subprocess.CalledProcessError, ValueError) as e:
    print(f"zfs list: {e}", file=sys.stderr)

# --- systemd units (backups) ----------------------------------------------
for unit in units:
    lbl = f'unit="{unit}"'
    try:
        props = dict(l.split("=", 1) for l in run(
            "systemctl", "show", "--timestamp=unix", unit,
            "-p", "Result,ActiveState,ExecMainExitTimestamp,ExecMainStatus").splitlines() if "=" in l)
    except subprocess.CalledProcessError as e:
        print(f"{unit}: {e}", file=sys.stderr)
        continue
    exited = props.get("ExecMainExitTimestamp", "").lstrip("@")
    ok = props.get("Result") == "success" and props.get("ExecMainStatus") == "0"
    add("systemd_unit_running", "1 while the unit is activating/active.", lbl,
        int(props.get("ActiveState") in ("activating", "active", "reloading")))
    if exited:
        add("systemd_unit_last_exit_timestamp_seconds", "When the unit's main process last exited.", lbl, exited)
        add("systemd_unit_last_run_success", "1 if the last run succeeded.", lbl, int(ok))
    last_ok = exited if (ok and exited) else previous("systemd_unit_last_success_timestamp_seconds", lbl)
    if last_ok:
        add("systemd_unit_last_success_timestamp_seconds", "When the unit last finished successfully.", lbl, last_ok)

# write then rename so node-exporter never reads a half-written file
with open(out + ".tmp", "w") as f:
    for name, (help_, series) in metrics.items():
        f.write(f"# HELP {name} {help_}\n# TYPE {name} gauge\n")
        f.writelines(f"{name}{{{labels}}} {value}\n" for labels, value in series)
os.replace(out + ".tmp", out)
