#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

DURATION_STEPS="${DURATION_STEPS:-5000}"
STEP_INTERVAL="${STEP_INTERVAL:-0.01}"
SWITCH_INTERVAL_SEC="${SWITCH_INTERVAL_SEC:-0.5}"
SWITCH_PROBABILITY="${SWITCH_PROBABILITY:-0.5}"
OUTPUT_CSV="${OUTPUT_CSV:-$ROOT_DIR/trcgen/master_collected_traces.csv}"
CLI_PATH="${CLI_PATH:-$ROOT_DIR/scripts/protocol_manager_rootns.sh}"
FLOW_ID="${FLOW_ID:-1}"
SEED="${SEED:-42}"
INITIAL_PROTOCOL="${INITIAL_PROTOCOL:-cubic}"
PROGRESS_EVERY="${PROGRESS_EVERY:-500}"
TRACES_DIR="${TRACES_DIR:-$ROOT_DIR/trcgen/traces}"
AUTO_DISCOVER="${AUTO_DISCOVER:-0}"
DEFAULT_DELAY_MS="${DEFAULT_DELAY_MS:-50}"
INCLUDE_UP_ONLY="${INCLUDE_UP_ONLY:-1}"

# Multi-environment mode (run outside Mahimahi with MULTI_ENV=1).
# Format:
#   env_name,up_trace,down_trace,delay_ms;env_name2,up_trace2,down_trace2,delay_ms2
# Trace paths can be absolute, or relative to TRACES_DIR.
ENV_SPECS="${ENV_SPECS:-\
synthetic_2mbps,synthetic_2mbps.up,synthetic_2mbps.up,50;\
att_lte,ATT-LTE-driving.up,ATT-LTE-driving.down,50;\
tmobile_umts,TMobile-UMTS-driving.down,TMobile-UMTS-driving.down,50;\
verizon_short,Verizon-LTE-short.up,Verizon-LTE-short.up,50}"
MULTI_ENV="${MULTI_ENV:-0}"
PER_ENV_STEPS="${PER_ENV_STEPS:-$DURATION_STEPS}"
COMBINE_OUTPUT="${COMBINE_OUTPUT:-1}"

resolve_trace_path() {
  local trace="$1"
  if [[ "$trace" = /* ]]; then
    printf "%s" "$trace"
  else
    printf "%s/%s" "$TRACES_DIR" "$trace"
  fi
}

sanitize_env_name() {
  local raw="$1"
  printf "%s" "$raw" | tr -cs '[:alnum:]' '_'
}

build_env_specs_from_traces_dir() {
  local dir="$1"
  local -a specs_local=()
  local up_path down_path base raw_name env_name

  shopt -s nullglob
  for up_path in "$dir"/*.up; do
    base="${up_path%.up}"
    down_path="${base}.down"
    raw_name="$(basename "$base")"
    env_name="$(sanitize_env_name "$raw_name")"

    if [[ -f "$down_path" ]]; then
      specs_local+=("${env_name},${up_path},${down_path},${DEFAULT_DELAY_MS}")
    elif [[ "$INCLUDE_UP_ONLY" == "1" ]]; then
      specs_local+=("${env_name},${up_path},${up_path},${DEFAULT_DELAY_MS}")
    fi
  done
  shopt -u nullglob

  if [[ "${#specs_local[@]}" -eq 0 ]]; then
    echo "No usable .up traces found in $dir"
    exit 1
  fi

  IFS=';'
  printf "%s" "${specs_local[*]}"
  unset IFS
}

run_single_env_collection() {
  if [[ -z "${MAHIMAHI_BASE:-}" ]]; then
    echo "MAHIMAHI_BASE is not set."
    echo "Run this script inside a Mahimahi shell (e.g., inside mm-delay/mm-link)."
    exit 1
  fi

  echo "Starting collection in Mahimahi namespace..."
  echo "Expect an iperf3 server reachable at MAHIMAHI_BASE=${MAHIMAHI_BASE}."
  echo "Protocol control path: $CLI_PATH"

  cd "$ROOT_DIR/python"
  "$PYTHON_BIN" collect_encoder_data.py \
    --cli-path "$CLI_PATH" \
    --flow-id "$FLOW_ID" \
    --output "$OUTPUT_CSV" \
    --duration-steps "$DURATION_STEPS" \
    --step-interval "$STEP_INTERVAL" \
    --switch-interval-sec "$SWITCH_INTERVAL_SEC" \
    --switch-probability "$SWITCH_PROBABILITY" \
    --initial-protocol "$INITIAL_PROTOCOL" \
    --progress-every "$PROGRESS_EVERY" \
    --seed "$SEED" \
    --run-iperf \
    --iperf-target "$MAHIMAHI_BASE"
}

if [[ "${1:-}" == "--single-env" ]]; then
  run_single_env_collection
  exit 0
fi

if [[ -n "${MAHIMAHI_BASE:-}" ]]; then
  run_single_env_collection
  exit 0
fi

if [[ "$MULTI_ENV" != "1" ]]; then
  echo "Not inside Mahimahi, and MULTI_ENV is not enabled."
  echo "Either:"
  echo "  1) run inside mm-delay/mm-link, or"
  echo "  2) run outside with MULTI_ENV=1 to sweep ENV_SPECS."
  exit 1
fi

command -v mm-delay >/dev/null 2>&1 || { echo "mm-delay not found in PATH"; exit 1; }
command -v mm-link >/dev/null 2>&1 || { echo "mm-link not found in PATH"; exit 1; }

if [[ "$AUTO_DISCOVER" == "1" ]]; then
  if [[ ! -d "$TRACES_DIR" ]]; then
    echo "TRACES_DIR does not exist: $TRACES_DIR"
    exit 1
  fi
  ENV_SPECS="$(build_env_specs_from_traces_dir "$TRACES_DIR")"
fi

echo "Running multi-environment collection from root namespace..."
echo "TRACES_DIR=$TRACES_DIR"
echo "AUTO_DISCOVER=$AUTO_DISCOVER"
echo "ENV_SPECS=$ENV_SPECS"
echo "COMBINE_OUTPUT=$COMBINE_OUTPUT"
echo "Base output CSV=$OUTPUT_CSV"

output_dir="$(dirname "$OUTPUT_CSV")"
output_file="$(basename "$OUTPUT_CSV")"
output_stem="${output_file%.csv}"
output_ext="${output_file##*.}"

IFS=';' read -r -a specs <<< "$ENV_SPECS"
for spec in "${specs[@]}"; do
  [[ -z "$spec" ]] && continue

  IFS=',' read -r env_name up_trace down_trace delay_ms <<< "$spec"
  if [[ -z "${env_name:-}" || -z "${up_trace:-}" || -z "${down_trace:-}" || -z "${delay_ms:-}" ]]; then
    echo "Invalid ENV_SPECS entry: $spec"
    exit 1
  fi

  up_path="$(resolve_trace_path "$up_trace")"
  down_path="$(resolve_trace_path "$down_trace")"
  if [[ ! -f "$up_path" ]]; then
    echo "Missing uplink trace for '$env_name': $up_path"
    exit 1
  fi
  if [[ ! -f "$down_path" ]]; then
    echo "Missing downlink trace for '$env_name': $down_path"
    exit 1
  fi

  if [[ "$COMBINE_OUTPUT" == "1" ]]; then
    env_output="$OUTPUT_CSV"
  else
    env_output="${output_dir}/${output_stem}_${env_name}.${output_ext}"
  fi

  echo
  echo "[env=$env_name] delay=${delay_ms}ms up=$(basename "$up_path") down=$(basename "$down_path")"
  echo "[env=$env_name] output=$env_output"

  mm-delay "$delay_ms" mm-link "$up_path" "$down_path" -- \
    /bin/bash -lc "
      cd '$ROOT_DIR' && \
      DURATION_STEPS='$PER_ENV_STEPS' \
      STEP_INTERVAL='$STEP_INTERVAL' \
      SWITCH_INTERVAL_SEC='$SWITCH_INTERVAL_SEC' \
      SWITCH_PROBABILITY='$SWITCH_PROBABILITY' \
      OUTPUT_CSV='$env_output' \
      CLI_PATH='$CLI_PATH' \
      FLOW_ID='$FLOW_ID' \
      SEED='$SEED' \
      INITIAL_PROTOCOL='$INITIAL_PROTOCOL' \
      PROGRESS_EVERY='$PROGRESS_EVERY' \
      PYTHON_BIN='$PYTHON_BIN' \
      ./scripts/collect_in_mahimahi.sh --single-env
    "
done

echo
echo "Multi-environment collection complete."
