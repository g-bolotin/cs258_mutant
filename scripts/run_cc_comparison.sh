#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

CLI_PATH="${CLI_PATH:-$ROOT_DIR/scripts/protocol_manager_rootns.sh}"
FLOW_ID="${FLOW_ID:-1}"
DURATION_STEPS="${DURATION_STEPS:-1500}"
STEP_INTERVAL="${STEP_INTERVAL:-0.01}"
PROTOCOLS="${PROTOCOLS:-cubic,hybla,bbr,westwood,veno,vegas,yeah,bic,htcp,illinois}"

RUN_IPERF="${RUN_IPERF:-1}"
IPERF_TARGET="${IPERF_TARGET:-${MAHIMAHI_BASE:-}}"
IPERF_PORT="${IPERF_PORT:-5201}"
IPERF_PAD_SEC="${IPERF_PAD_SEC:-8}"

MODEL_PATH="${MODEL_PATH:-$ROOT_DIR/mutant_autoencoder.pth}"
SCALER_PATH="${SCALER_PATH:-$ROOT_DIR/mutant_scaler.save}"
ALPHA="${ALPHA:-0.5}"
GAMMA="${GAMMA:-0.95}"
MPTS_K="${MPTS_K:-6}"
MPTS_BUDGET="${MPTS_BUDGET:-100}"
RTT_PENALTY_WEIGHT="${RTT_PENALTY_WEIGHT:-0.1}"

OUT_DIR="${OUT_DIR:-}"
SKIP_MUTANT="${SKIP_MUTANT:-0}"
MUTANT_ONLY="${MUTANT_ONLY:-0}"
TRACE_SWEEP="${TRACE_SWEEP:-0}"
TRACES_DIR="${TRACES_DIR:-$ROOT_DIR/trcgen/traces}"
TRACE_SPECS="${TRACE_SPECS:-}"
DEFAULT_DELAY_MS="${DEFAULT_DELAY_MS:-50}"
INCLUDE_UP_ONLY="${INCLUDE_UP_ONLY:-1}"
AUTO_DURATION="${AUTO_DURATION:-0}"
AUTO_DURATION_SCALE="${AUTO_DURATION_SCALE:-1.0}"
AUTO_DURATION_EXTRA_STEPS="${AUTO_DURATION_EXTRA_STEPS:-0}"
AUTO_DURATION_MIN_STEPS="${AUTO_DURATION_MIN_STEPS:-1}"
UPLINK_QUEUE="${UPLINK_QUEUE:-droptail}"
UPLINK_QUEUE_ARGS="${UPLINK_QUEUE_ARGS:-packets=100}"
DOWNLINK_QUEUE="${DOWNLINK_QUEUE:-droptail}"
DOWNLINK_QUEUE_ARGS="${DOWNLINK_QUEUE_ARGS:-packets=100}"

cmd=(
  "$PYTHON_BIN" "$ROOT_DIR/python/compare_cc.py"
  --python-bin "$PYTHON_BIN"
  --cli-path "$CLI_PATH"
  --flow-id "$FLOW_ID"
  --duration-steps "$DURATION_STEPS"
  --step-interval "$STEP_INTERVAL"
  --protocols "$PROTOCOLS"
  --model-path "$MODEL_PATH"
  --scaler-path "$SCALER_PATH"
  --alpha "$ALPHA"
  --gamma "$GAMMA"
  --mpts-k "$MPTS_K"
  --mpts-budget "$MPTS_BUDGET"
  --rtt-penalty-weight "$RTT_PENALTY_WEIGHT"
  --iperf-port "$IPERF_PORT"
  --iperf-pad-sec "$IPERF_PAD_SEC"
)

if [[ "$RUN_IPERF" == "1" ]]; then
  if [[ -z "$IPERF_TARGET" && "$TRACE_SWEEP" != "1" ]]; then
    echo "RUN_IPERF=1 but no IPERF_TARGET or MAHIMAHI_BASE is set." >&2
    exit 1
  fi
  cmd+=(--run-iperf)
  if [[ -n "$IPERF_TARGET" ]]; then
    cmd+=(--iperf-target "$IPERF_TARGET")
  fi
fi

if [[ "$SKIP_MUTANT" == "1" ]]; then
  cmd+=(--skip-mutant)
fi
if [[ "$MUTANT_ONLY" == "1" ]]; then
  cmd+=(--mutant-only)
fi

if [[ "$TRACE_SWEEP" == "1" ]]; then
  cmd+=(
    --trace-sweep
    --traces-dir "$TRACES_DIR"
    --default-delay-ms "$DEFAULT_DELAY_MS"
    --uplink-queue "$UPLINK_QUEUE"
    --uplink-queue-args "$UPLINK_QUEUE_ARGS"
    --downlink-queue "$DOWNLINK_QUEUE"
    --downlink-queue-args "$DOWNLINK_QUEUE_ARGS"
  )
  if [[ "$INCLUDE_UP_ONLY" == "1" ]]; then
    cmd+=(--include-up-only)
  else
    cmd+=(--no-include-up-only)
  fi
  if [[ -n "$TRACE_SPECS" ]]; then
    cmd+=(--trace-specs "$TRACE_SPECS")
  fi
  if [[ "$AUTO_DURATION" == "1" ]]; then
    cmd+=(
      --auto-duration
      --auto-duration-scale "$AUTO_DURATION_SCALE"
      --auto-duration-extra-steps "$AUTO_DURATION_EXTRA_STEPS"
      --auto-duration-min-steps "$AUTO_DURATION_MIN_STEPS"
    )
  fi
fi

if [[ -n "$OUT_DIR" ]]; then
  cmd+=(--out-dir "$OUT_DIR")
fi

exec "${cmd[@]}"
