#!/usr/bin/env bash
# Per-container GPU usage for node-exporter's textfile collector.
#
# nvidia-smi only reports host PIDs, so each PID is mapped to its container
# through /proc/<pid>/cgroup and summed per container. Processes outside
# docker are reported as container="host".
#
# Usage: gpu-procs.sh [out_dir] [--once]     (INTERVAL env, default 15s)
set -uo pipefail

out_dir=${1:-/srv/monitoring/textfile}
once=${2:-}
interval=${INTERVAL:-15}
out=$out_dir/gpu_procs.prom

# One line per process: gpu pid sm mem enc dec fb_mib ("-" becomes 0).
# Columns are found from the header since they vary between driver versions.
pmon() {
  nvidia-smi pmon -c 1 -s um | awk '
    /^# *gpu/ { for (i = 2; i <= NF; i++) col[$i] = i - 1; next }
    /^#/      { next }
    {
      n = split("gpu pid sm mem enc dec fb", want, " "); line = ""
      for (k = 1; k <= n; k++) { x = $(col[want[k]]); if (x == "-") x = 0; line = line x " " }
      print line
    }'
}

collect() {
  local -A names=() procs=() sm=() mem=() enc=() dec=() fb=()
  local id name gpu pid s m e d f cid key

  while read -r id name; do names[$id]=$name; done \
    < <(docker ps --no-trunc --format '{{.ID}} {{.Names}}')

  while read -r gpu pid s m e d f; do
    [[ $pid =~ ^[0-9]+$ && $pid != 0 ]] || continue
    cid=$(grep -oPm1 'docker-\K[0-9a-f]{64}' "/proc/$pid/cgroup" 2>/dev/null)
    if [[ -n $cid ]]; then name=${names[$cid]:-unknown}; else name=host; fi
    key="gpu=\"$gpu\",container=\"$name\""
    procs[$key]=$(( ${procs[$key]:-0} + 1 ))
    sm[$key]=$((  ${sm[$key]:-0}  + s ))
    mem[$key]=$(( ${mem[$key]:-0} + m ))
    enc[$key]=$(( ${enc[$key]:-0} + e ))
    dec[$key]=$(( ${dec[$key]:-0} + d ))
    fb[$key]=$((  ${fb[$key]:-0}  + f * 1024 * 1024 ))
  done < <(pmon)

  emit() { # name help array
    local -n arr=$3
    echo "# HELP gpu_container_$1 $2"
    echo "# TYPE gpu_container_$1 gauge"
    for key in "${!arr[@]}"; do echo "gpu_container_$1{$key} ${arr[$key]}"; done
  }
  emit processes      "GPU processes per container."                  procs
  emit sm_percent     "SM (compute) utilisation per container."       sm
  emit mem_percent    "Memory bandwidth utilisation per container."   mem
  emit enc_percent    "NVENC utilisation per container."              enc
  emit dec_percent    "NVDEC utilisation per container."              dec
  emit memory_bytes   "Framebuffer memory used per container."        fb
}

while true; do
  # write then rename so node-exporter never reads a half-written file
  if collect > "$out.tmp"; then mv "$out.tmp" "$out"; fi
  [[ $once == --once ]] && break
  sleep "$interval"
done
