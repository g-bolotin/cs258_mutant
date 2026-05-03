#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

TRACES_DIR="${TRACES_DIR:-$ROOT_DIR/../mahimahi/traces}"
DELAY_MS="${DELAY_MS:-10}"
MUTANT_CLI_TIMEOUT_SEC="${MUTANT_CLI_TIMEOUT_SEC:-12}"

# All fixed CC algorithms supported by protocol_manager.
PROTOCOLS="${PROTOCOLS:-cubic,hybla,bbr,westwood,veno,vegas,yeah,bic,htcp,illinois}"

# Default to fixed-CC sweep only. Set INCLUDE_MUTANT=1 to include Mutant run too.
INCLUDE_MUTANT="${INCLUDE_MUTANT:-0}"
if [[ "$INCLUDE_MUTANT" == "1" ]]; then
  SKIP_MUTANT="${SKIP_MUTANT:-0}"
else
  SKIP_MUTANT="${SKIP_MUTANT:-1}"
fi

RUN_IPERF="${RUN_IPERF:-1}"
TRACE_SWEEP=1
MUTANT_ONLY=0
AUTO_DURATION="${AUTO_DURATION:-1}"
UPLINK_QUEUE="${UPLINK_QUEUE:-droptail}"
UPLINK_QUEUE_ARGS="${UPLINK_QUEUE_ARGS:-packets=10}"
DOWNLINK_QUEUE="${DOWNLINK_QUEUE:-droptail}"
DOWNLINK_QUEUE_ARGS="${DOWNLINK_QUEUE_ARGS:-packets=10}"

if [[ ! -d "$TRACES_DIR" ]]; then
  echo "TRACES_DIR does not exist: $TRACES_DIR" >&2
  exit 1
fi

build_trace_specs() {
  local dir="$1"
  local delay_ms="$2"
  local -a specs=()
  local up base down name

  shopt -s nullglob
  for up in "$dir"/TMobile-*.up "$dir"/Verizon-*.up; do
    base="${up%.up}"
    down="${base}.down"
    [[ -f "$down" ]] || continue
    name="$(basename "$base" | tr '-' '_')"
    specs+=("${name},${up},${down},${delay_ms}")
  done
  shopt -u nullglob

  if [[ "${#specs[@]}" -eq 0 ]]; then
    echo "No TMobile/Verizon .up/.down trace pairs found in: $dir" >&2
    exit 1
  fi

  local IFS=';'
  printf "%s" "${specs[*]}"
}

TRACE_SPECS="${TRACE_SPECS:-$(build_trace_specs "$TRACES_DIR" "$DELAY_MS")}"

echo "Running TMobile + Verizon CC sweep"
echo "TRACES_DIR=$TRACES_DIR"
echo "DELAY_MS=$DELAY_MS"
echo "SKIP_MUTANT=$SKIP_MUTANT (INCLUDE_MUTANT=$INCLUDE_MUTANT)"
echo "PROTOCOLS=$PROTOCOLS"
echo "RUN_IPERF=$RUN_IPERF"
echo "AUTO_DURATION=$AUTO_DURATION"

export MUTANT_CLI_TIMEOUT_SEC
export TRACE_SWEEP
export MUTANT_ONLY
export RUN_IPERF
export TRACES_DIR
export TRACE_SPECS
export DEFAULT_DELAY_MS="$DELAY_MS"
export PROTOCOLS
export SKIP_MUTANT
export AUTO_DURATION
export UPLINK_QUEUE
export UPLINK_QUEUE_ARGS
export DOWNLINK_QUEUE
export DOWNLINK_QUEUE_ARGS

exec "$ROOT_DIR/scripts/run_cc_comparison.sh"
