#!/usr/bin/env python3
import argparse
import csv
import json
import math
import os
import shlex
import shutil
import subprocess
import sys
import time
from collections import Counter, deque
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import torch

from autoencoder import MutantAutoencoder
from env import MutantEnv
from learner import LinUCBAgent
from mpts import run_mpts
from reward import compute_reward


DEFAULT_PROTOCOLS = [
    "cubic",
    "hybla",
    "bbr",
    "westwood",
    "veno",
    "vegas",
    "yeah",
    "bic",
    "htcp",
    "illinois",
]

BASE_KEYS = [
    "cwnd",
    "rtt_ms",
    "min_rtt",
    "advmss",
    "delivered",
    "retrans_out",
    "delivery_rate",
    "prev_proto",
    "crt_proto",
    "loss_rate",
]

TEMPORAL_KEYS = [
    "smoothed_rtt",
    "mdev_us",
    "lost_out",
    "in_flight",
    "throughput_mbps",
]


class NetworkHistory:
    class _RollingWindowStats:
        def __init__(self, maxlen, num_features):
            self.maxlen = maxlen
            self.num_features = num_features
            self.entries = deque()
            self.sum = np.zeros(num_features, dtype=np.float64)
            self.min_deques = [deque() for _ in range(num_features)]
            self.max_deques = [deque() for _ in range(num_features)]
            self.next_index = 0

        def append(self, values):
            idx = self.next_index
            self.next_index += 1

            arr = np.asarray(values, dtype=np.float64)
            self.entries.append((idx, arr))
            self.sum += arr

            for i in range(self.num_features):
                v = float(arr[i])
                min_q = self.min_deques[i]
                while min_q and min_q[-1][1] >= v:
                    min_q.pop()
                min_q.append((idx, v))

                max_q = self.max_deques[i]
                while max_q and max_q[-1][1] <= v:
                    max_q.pop()
                max_q.append((idx, v))

            if len(self.entries) > self.maxlen:
                old_idx, old_arr = self.entries.popleft()
                self.sum -= old_arr
                for i in range(self.num_features):
                    min_q = self.min_deques[i]
                    if min_q and min_q[0][0] == old_idx:
                        min_q.popleft()
                    max_q = self.max_deques[i]
                    if max_q and max_q[0][0] == old_idx:
                        max_q.popleft()

        def empty(self):
            return len(self.entries) == 0

        def stats(self):
            if self.empty():
                zeros = np.zeros(self.num_features, dtype=np.float64)
                return zeros, zeros, zeros

            count = len(self.entries)
            mins = np.array([q[0][1] for q in self.min_deques], dtype=np.float64)
            maxs = np.array([q[0][1] for q in self.max_deques], dtype=np.float64)
            means = self.sum / count
            return mins, maxs, means

    def __init__(self, track_keys):
        self.track_keys = track_keys
        num_features = len(self.track_keys)
        self.short_win = self._RollingWindowStats(maxlen=10, num_features=num_features)
        self.med_win = self._RollingWindowStats(maxlen=200, num_features=num_features)
        self.long_win = self._RollingWindowStats(maxlen=1000, num_features=num_features)

    def update(self, metrics):
        current_vals = [float(metrics.get(k, 0.0) or 0.0) for k in self.track_keys]
        self.short_win.append(current_vals)
        self.med_win.append(current_vals)
        self.long_win.append(current_vals)

    def get_temporal_features(self):
        temporal_features = []
        if self.short_win.empty():
            return [0.0] * (len(self.track_keys) * 3 * 3)

        for window in [self.short_win, self.med_win, self.long_win]:
            mins, maxs, means = window.stats()
            temporal_features.extend(mins.tolist() + maxs.tolist() + means.tolist())
        return temporal_features


def parse_protocols(raw):
    out = []
    for token in raw.split(","):
        p = token.strip().lower()
        if p:
            out.append(p)
    return out


def sanitize_name(raw):
    safe = "".join(ch if ch.isalnum() else "_" for ch in raw.strip())
    while "__" in safe:
        safe = safe.replace("__", "_")
    return safe.strip("_") or "trace"


def resolve_trace_path(base_dir, trace_path):
    p = Path(trace_path)
    if p.is_absolute():
        return p
    return (base_dir / trace_path).resolve()


def parse_trace_specs(specs_raw, traces_dir):
    specs = []
    for entry in specs_raw.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        parts = [x.strip() for x in entry.split(",")]
        if len(parts) != 4:
            raise SystemExit(f"Invalid trace spec: '{entry}' (expected name,up,down,delay_ms)")
        name, up, down, delay_ms = parts
        up_path = resolve_trace_path(traces_dir, up)
        down_path = resolve_trace_path(traces_dir, down)
        if not up_path.exists():
            raise SystemExit(f"Missing uplink trace for '{name}': {up_path}")
        if not down_path.exists():
            raise SystemExit(f"Missing downlink trace for '{name}': {down_path}")
        specs.append(
            {
                "name": sanitize_name(name),
                "up_path": str(up_path),
                "down_path": str(down_path),
                "delay_ms": int(delay_ms),
            }
        )
    if not specs:
        raise SystemExit("No trace specs provided.")
    return specs


def trace_duration_ms(trace_path):
    """
    Mahimahi trace files are timestamp lists (ms) per packet opportunity.
    Duration is approximated by the largest timestamp plus one millisecond.
    """
    max_ts = None
    with open(trace_path, "r", encoding="utf-8") as f:
        for line in f:
            raw = line.strip()
            if not raw:
                continue
            try:
                ts = int(float(raw))
            except ValueError:
                continue
            if max_ts is None or ts > max_ts:
                max_ts = ts

    if max_ts is None:
        return 0
    return max_ts + 1


def duration_steps_from_trace(trace_path, step_interval, scale=1.0, extra_steps=0, min_steps=1):
    dur_ms = trace_duration_ms(trace_path)
    if dur_ms <= 0:
        return max(min_steps, extra_steps if extra_steps > 0 else 1), dur_ms
    dur_sec = (dur_ms / 1000.0) * scale
    steps = int(math.ceil(dur_sec / step_interval)) + int(extra_steps)
    return max(min_steps, steps), dur_ms


def discover_trace_specs(traces_dir, default_delay_ms=50, include_up_only=True):
    traces_dir = Path(traces_dir).resolve()
    if not traces_dir.exists():
        raise SystemExit(f"Traces dir does not exist: {traces_dir}")

    specs = []
    up_files = sorted(traces_dir.glob("*.up"))
    for up_path in up_files:
        stem = up_path.with_suffix("")
        down_path = stem.with_suffix(".down")
        name = sanitize_name(stem.name)
        if down_path.exists():
            specs.append(
                {
                    "name": name,
                    "up_path": str(up_path.resolve()),
                    "down_path": str(down_path.resolve()),
                    "delay_ms": int(default_delay_ms),
                }
            )
        elif include_up_only:
            specs.append(
                {
                    "name": name,
                    "up_path": str(up_path.resolve()),
                    "down_path": str(up_path.resolve()),
                    "delay_ms": int(default_delay_ms),
                }
            )

    if not specs:
        raise SystemExit(f"No usable traces discovered in {traces_dir}")
    return specs


def percentile(values, q):
    if not values:
        return 0.0
    vals = sorted(values)
    idx = max(0, min(len(vals) - 1, math.ceil((q / 100.0) * len(vals)) - 1))
    return float(vals[idx])


def start_iperf_client(target, port, duration_secs, json_out_path):
    cmd = [
        "iperf3",
        "-c",
        target,
        "-p",
        str(port),
        "-t",
        str(duration_secs),
        "-J",
        "-i",
        "1",
    ]
    out_f = open(json_out_path, "w", encoding="utf-8")
    proc = subprocess.Popen(cmd, stdout=out_f, stderr=subprocess.STDOUT, text=True)
    return proc, out_f, cmd


def parse_iperf_json_to_csv(iperf_json_path, out_csv_path):
    if not os.path.exists(iperf_json_path):
        return 0

    with open(iperf_json_path, "r", encoding="utf-8") as f:
        raw = f.read().strip()
    if not raw:
        return 0

    # iperf can emit extra diagnostic text before/after the JSON blob.
    # Parse the first valid JSON object and ignore trailing data.
    decoder = json.JSONDecoder()
    data = None
    for i, ch in enumerate(raw):
        if ch != "{":
            continue
        try:
            obj, _end = decoder.raw_decode(raw, idx=i)
            if isinstance(obj, dict):
                data = obj
                break
        except json.JSONDecodeError:
            continue

    if data is None:
        return 0
    intervals = data.get("intervals", [])

    rows = []
    for interval in intervals:
        streams = interval.get("streams") or []
        obj = interval.get("sum") or (streams[0] if streams else {})
        rows.append(
            {
                "start_sec": obj.get("start", 0.0),
                "end_sec": obj.get("end", 0.0),
                "seconds": obj.get("seconds", 0.0),
                "bits_per_second": obj.get("bits_per_second", 0.0),
                "retransmits": obj.get("retransmits", 0),
                "snd_cwnd": obj.get("snd_cwnd", 0),
                "rtt_us": obj.get("rtt", 0),
                "rttvar_us": obj.get("rttvar", 0),
                "omitted": obj.get("omitted", False),
            }
        )

    with open(out_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "start_sec",
                "end_sec",
                "seconds",
                "bits_per_second",
                "retransmits",
                "snd_cwnd",
                "rtt_us",
                "rttvar_us",
                "omitted",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    return len(rows)


def aggregate_trace_metrics(rows):
    if not rows:
        return {
            "samples": 0,
            "avg_tp_mbps": 0.0,
            "p50_tp_mbps": 0.0,
            "p95_rtt_ms": 0.0,
            "avg_loss_rate": 0.0,
            "avg_reward": 0.0,
            "switches": 0,
            "dominant_protocol": "n/a",
        }

    throughput = [float(r["throughput_mbps"]) for r in rows]
    rtt = [float(r["rtt_ms"]) for r in rows]
    loss_rate = [float(r["loss_rate"]) for r in rows]
    rewards = [float(r["reward"]) for r in rows]
    actions = [r["action"] for r in rows]
    observed = [r["observed_protocol"] for r in rows]

    switches = 0
    for i in range(1, len(actions)):
        if actions[i] != actions[i - 1]:
            switches += 1

    dominant_protocol = Counter(observed).most_common(1)[0][0] if observed else "n/a"
    return {
        "samples": len(rows),
        "avg_tp_mbps": float(np.mean(throughput)),
        "p50_tp_mbps": percentile(throughput, 50),
        "p95_rtt_ms": percentile(rtt, 95),
        "avg_loss_rate": float(np.mean(loss_rate)),
        "avg_reward": float(np.mean(rewards)),
        "switches": switches,
        "dominant_protocol": dominant_protocol,
    }


def run_fixed_controller(env, protocol, duration_steps, step_interval, trace_writer, rtt_penalty_weight=0.1):
    rows = []
    env.reset(initial_protocol=protocol)
    env.set_protocol(protocol)
    start_ts = time.monotonic()

    for step in range(duration_steps):
        metrics = env.get_metrics()
        if metrics:
            reward = compute_reward(metrics, rtt_penalty_weight=rtt_penalty_weight)
            row = {
                "step": step,
                "elapsed_sec": round(time.monotonic() - start_ts, 6),
                "action": protocol,
                "observed_protocol": metrics.get("protocol", "unknown"),
                "throughput_mbps": float(metrics.get("throughput_mbps", 0.0)),
                "rtt_ms": float(metrics.get("rtt_ms", 0.0)),
                "smoothed_rtt": float(metrics.get("smoothed_rtt", 0.0)),
                "cwnd": float(metrics.get("cwnd", 0.0)),
                "loss_rate": float(metrics.get("loss_rate", 0.0)),
                "reward": float(reward),
            }
            trace_writer.writerow(row)
            rows.append(row)

        time.sleep(step_interval)
    return rows


def run_mutant_controller(
    env,
    protocols,
    model,
    scaler,
    duration_steps,
    step_interval,
    trace_writer,
    alpha=0.5,
    gamma=0.95,
    mpts_k=6,
    mpts_budget=100,
    rtt_penalty_weight=0.1,
):
    rows = []
    model.eval()
    env.reset(initial_protocol="cubic")
    selected_protocols = run_mpts(
        env,
        protocols,
        target_k=min(mpts_k, len(protocols)),
        T=mpts_budget,
        step_interval=step_interval,
        rtt_penalty_weight=rtt_penalty_weight,
    )
    if not selected_protocols:
        selected_protocols = list(protocols)

    agent = LinUCBAgent(selected_protocols, latent_dim=16, alpha=alpha, gamma=gamma)
    history = NetworkHistory(track_keys=TEMPORAL_KEYS)
    start_ts = time.monotonic()

    for step in range(duration_steps):
        metrics = env.get_metrics()
        if not metrics:
            time.sleep(step_interval)
            continue

        history.update(metrics)
        base_features = [metrics.get(k, 0.0) for k in BASE_KEYS]
        temporal_features = history.get_temporal_features()
        raw_features = base_features + temporal_features

        scaled_features = scaler.transform([raw_features])[0]
        state_tensor = torch.FloatTensor(scaled_features).unsqueeze(0).unsqueeze(0)

        with torch.no_grad():
            latent_tensor = model.encode(state_tensor)
            z_t = latent_tensor.numpy().flatten()

        action = agent.select_action(z_t)
        env.set_protocol(action)
        time.sleep(step_interval)

        new_metrics = env.get_metrics()
        if not new_metrics:
            continue

        reward = compute_reward(new_metrics, rtt_penalty_weight=rtt_penalty_weight)
        agent.update(action, z_t, reward)

        row = {
            "step": step,
            "elapsed_sec": round(time.monotonic() - start_ts, 6),
            "action": action,
            "observed_protocol": new_metrics.get("protocol", "unknown"),
            "throughput_mbps": float(new_metrics.get("throughput_mbps", 0.0)),
            "rtt_ms": float(new_metrics.get("rtt_ms", 0.0)),
            "smoothed_rtt": float(new_metrics.get("smoothed_rtt", 0.0)),
            "cwnd": float(new_metrics.get("cwnd", 0.0)),
            "loss_rate": float(new_metrics.get("loss_rate", 0.0)),
            "reward": float(reward),
        }
        trace_writer.writerow(row)
        rows.append(row)

    return rows, selected_protocols


def run_one_experiment(
    run_name,
    mode,
    env,
    out_dir,
    duration_steps,
    step_interval,
    run_iperf,
    iperf_target,
    iperf_port,
    iperf_pad_sec,
    fixed_protocol=None,
    mutant_ctx=None,
    rtt_penalty_weight=0.1,
    shared_iperf_csv="",
    shared_iperf_intervals=0,
    shared_iperf_cmd="",
):
    safe_name = run_name.replace(" ", "_")
    trace_csv = os.path.join(out_dir, f"{safe_name}_trace.csv")
    # Raw iperf JSON is only an intermediate for CSV conversion.
    iperf_json = os.path.join(out_dir, f".{safe_name}_iperf_raw.json")
    iperf_csv = os.path.join(out_dir, f"{safe_name}_iperf_intervals.csv")

    iperf_proc = None
    iperf_file = None
    iperf_cmd = None
    if run_iperf:
        duration_secs = max(1, int(duration_steps * step_interval) + iperf_pad_sec)
        iperf_proc, iperf_file, iperf_cmd = start_iperf_client(
            target=iperf_target,
            port=iperf_port,
            duration_secs=duration_secs,
            json_out_path=iperf_json,
        )
        time.sleep(1.0)

    with open(trace_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "step",
                "elapsed_sec",
                "action",
                "observed_protocol",
                "throughput_mbps",
                "rtt_ms",
                "smoothed_rtt",
                "cwnd",
                "loss_rate",
                "reward",
            ],
        )
        writer.writeheader()

        if mode == "fixed":
            rows = run_fixed_controller(
                env=env,
                protocol=fixed_protocol,
                duration_steps=duration_steps,
                step_interval=step_interval,
                trace_writer=writer,
                rtt_penalty_weight=rtt_penalty_weight,
            )
            selected_protocols = [fixed_protocol]
        elif mode == "mutant":
            rows, selected_protocols = run_mutant_controller(
                env=env,
                protocols=mutant_ctx["protocol_pool"],
                model=mutant_ctx["model"],
                scaler=mutant_ctx["scaler"],
                duration_steps=duration_steps,
                step_interval=step_interval,
                trace_writer=writer,
                alpha=mutant_ctx["alpha"],
                gamma=mutant_ctx["gamma"],
                mpts_k=mutant_ctx["mpts_k"],
                mpts_budget=mutant_ctx["mpts_budget"],
                rtt_penalty_weight=rtt_penalty_weight,
            )
        else:
            raise ValueError(f"Unsupported mode: {mode}")

    iperf_intervals = 0
    if iperf_proc is not None:
        try:
            iperf_proc.wait(timeout=max(5, int(duration_steps * step_interval) + iperf_pad_sec + 15))
        except subprocess.TimeoutExpired:
            iperf_proc.terminate()
            iperf_proc.wait()
        finally:
            iperf_file.close()
        try:
            iperf_intervals = parse_iperf_json_to_csv(iperf_json, iperf_csv)
        except Exception as e:
            print(f"[warn] failed to parse iperf output for {run_name}: {e}")
            iperf_intervals = 0
        finally:
            if os.path.exists(iperf_json):
                os.remove(iperf_json)

    agg = aggregate_trace_metrics(rows)
    agg.update(
        {
            "run_name": run_name,
            "mode": mode,
            "fixed_protocol": fixed_protocol or "",
            "selected_protocols": ",".join(selected_protocols),
            "trace_csv": trace_csv,
            "iperf_csv": iperf_csv if run_iperf else shared_iperf_csv,
            "iperf_intervals": iperf_intervals if run_iperf else shared_iperf_intervals,
            "iperf_cmd": (" ".join(iperf_cmd) if iperf_cmd else shared_iperf_cmd),
        }
    )
    return agg


def run_single_comparison(args, here, root, out_dir):
    protocols = parse_protocols(args.protocols)
    if not protocols:
        raise SystemExit("No protocols specified.")

    cli_path = (here / args.cli_path).resolve() if not os.path.isabs(args.cli_path) else Path(args.cli_path)
    if not cli_path.exists():
        raise SystemExit(f"CLI path does not exist: {cli_path}")

    if args.run_iperf and not args.iperf_target:
        raise SystemExit("Missing --iperf-target (or MAHIMAHI_BASE env var).")

    env = MutantEnv(cli_path=str(cli_path), flow_id=args.flow_id)

    mutant_ctx = None
    if not args.skip_mutant:
        model_path = (here / args.model_path).resolve() if not os.path.isabs(args.model_path) else Path(args.model_path)
        scaler_path = (here / args.scaler_path).resolve() if not os.path.isabs(args.scaler_path) else Path(args.scaler_path)
        if not model_path.exists():
            raise SystemExit(f"Model checkpoint not found: {model_path}")
        if not scaler_path.exists():
            raise SystemExit(f"Scaler not found: {scaler_path}")

        model = MutantAutoencoder(input_dim=55, hidden_dim=32, latent_dim=16)
        model.load_state_dict(torch.load(str(model_path), map_location="cpu"))
        scaler = joblib.load(str(scaler_path))

        mutant_ctx = {
            "protocol_pool": protocols,
            "model": model,
            "scaler": scaler,
            "alpha": args.alpha,
            "gamma": args.gamma,
            "mpts_k": args.mpts_k,
            "mpts_budget": args.mpts_budget,
        }

    summary_rows = []
    shared_iperf_csv = ""
    shared_iperf_intervals = 0
    shared_iperf_cmd = ""
    shared_iperf_proc = None
    shared_iperf_file = None
    shared_iperf_json = ""

    print(f"Output directory: {out_dir}")
    print(f"Fixed protocols: {protocols}")
    print(f"Mutant-only mode: {args.mutant_only}")
    print(f"Mutant enabled: {not args.skip_mutant}")
    print(f"Duration steps={args.duration_steps}, interval={args.step_interval}s")

    # One iperf client per trace run (shared across all algorithms) for stability.
    if args.run_iperf:
        total_runs = (0 if args.mutant_only else len(protocols)) + (0 if args.skip_mutant else 1)
        duration_secs = max(1, int(total_runs * args.duration_steps * args.step_interval) + args.iperf_pad_sec)
        shared_iperf_json = str(out_dir / ".trace_iperf_raw.json")
        shared_iperf_csv = str(out_dir / "trace_iperf_intervals.csv")
        shared_iperf_proc, shared_iperf_file, iperf_cmd = start_iperf_client(
            target=args.iperf_target,
            port=args.iperf_port,
            duration_secs=duration_secs,
            json_out_path=shared_iperf_json,
        )
        shared_iperf_cmd = " ".join(iperf_cmd)
        print(f"[iperf] shared client for trace: duration={duration_secs}s")
        time.sleep(1.0)

    if not args.mutant_only:
        for p in protocols:
            run_name = f"fixed_{p}"
            print(f"[run] {run_name}")
            row = run_one_experiment(
                run_name=run_name,
                mode="fixed",
                env=env,
                out_dir=str(out_dir),
                duration_steps=args.duration_steps,
                step_interval=args.step_interval,
                run_iperf=False,
                iperf_target=args.iperf_target,
                iperf_port=args.iperf_port,
                iperf_pad_sec=args.iperf_pad_sec,
                fixed_protocol=p,
                rtt_penalty_weight=args.rtt_penalty_weight,
                shared_iperf_csv=shared_iperf_csv,
                shared_iperf_intervals=shared_iperf_intervals,
                shared_iperf_cmd=shared_iperf_cmd,
            )
            summary_rows.append(row)

    if not args.skip_mutant:
        run_name = "mutant"
        print(f"[run] {run_name}")
        row = run_one_experiment(
            run_name=run_name,
            mode="mutant",
            env=env,
            out_dir=str(out_dir),
            duration_steps=args.duration_steps,
            step_interval=args.step_interval,
            run_iperf=False,
            iperf_target=args.iperf_target,
            iperf_port=args.iperf_port,
            iperf_pad_sec=args.iperf_pad_sec,
            mutant_ctx=mutant_ctx,
            rtt_penalty_weight=args.rtt_penalty_weight,
            shared_iperf_csv=shared_iperf_csv,
            shared_iperf_intervals=shared_iperf_intervals,
            shared_iperf_cmd=shared_iperf_cmd,
        )
        summary_rows.append(row)

    if args.run_iperf and shared_iperf_proc is not None:
        try:
            expected_secs = max(5, int(((0 if args.mutant_only else len(protocols)) + (0 if args.skip_mutant else 1)) * args.duration_steps * args.step_interval) + args.iperf_pad_sec + 15)
            shared_iperf_proc.wait(timeout=expected_secs)
        except subprocess.TimeoutExpired:
            shared_iperf_proc.terminate()
            shared_iperf_proc.wait()
        finally:
            shared_iperf_file.close()
        try:
            shared_iperf_intervals = parse_iperf_json_to_csv(shared_iperf_json, shared_iperf_csv)
        except Exception as e:
            print(f"[warn] failed to parse shared iperf output: {e}")
            shared_iperf_intervals = 0
        finally:
            if os.path.exists(shared_iperf_json):
                os.remove(shared_iperf_json)

        for row in summary_rows:
            row["iperf_csv"] = shared_iperf_csv
            row["iperf_intervals"] = shared_iperf_intervals
            row["iperf_cmd"] = shared_iperf_cmd

    summary_csv = out_dir / "summary.csv"
    fieldnames = [
        "run_name",
        "mode",
        "fixed_protocol",
        "selected_protocols",
        "samples",
        "avg_tp_mbps",
        "p50_tp_mbps",
        "p95_rtt_ms",
        "avg_loss_rate",
        "avg_reward",
        "switches",
        "dominant_protocol",
        "iperf_intervals",
        "trace_csv",
        "iperf_csv",
        "iperf_cmd",
    ]
    with open(summary_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary_rows)
    print(f"Done. Summary written to: {summary_csv}")
    return summary_rows


def run_trace_sweep(args, here, root, out_dir):
    if not shutil_which("mm-delay") or not shutil_which("mm-link"):
        raise SystemExit("trace-sweep mode requires mm-delay and mm-link in PATH.")

    traces_dir = (here / args.traces_dir).resolve() if not os.path.isabs(args.traces_dir) else Path(args.traces_dir)

    if args.trace_specs:
        specs = parse_trace_specs(args.trace_specs, traces_dir)
    else:
        specs = discover_trace_specs(
            traces_dir=traces_dir,
            default_delay_ms=args.default_delay_ms,
            include_up_only=args.include_up_only,
        )

    print(f"Sweep output directory: {out_dir}")
    print(f"Sweep traces ({len(specs)}): {[s['name'] for s in specs]}")

    combined_rows = []
    script_path = (here / "compare_cc.py").resolve()

    for spec in specs:
        trace_name = spec["name"]
        trace_out_dir = (out_dir / trace_name).resolve()
        trace_out_dir.mkdir(parents=True, exist_ok=True)
        per_trace_steps = int(args.duration_steps)
        trace_dur_ms = ""
        if args.auto_duration:
            per_trace_steps, dur_ms = duration_steps_from_trace(
                trace_path=spec["up_path"],
                step_interval=args.step_interval,
                scale=args.auto_duration_scale,
                extra_steps=args.auto_duration_extra_steps,
                min_steps=args.auto_duration_min_steps,
            )
            trace_dur_ms = str(dur_ms)

        sub_cmd = [
            args.python_bin,
            str(script_path),
            "--_single-run",
            "--cli-path",
            str(args.cli_path),
            "--flow-id",
            str(args.flow_id),
            "--duration-steps",
            str(per_trace_steps),
            "--step-interval",
            str(args.step_interval),
            "--protocols",
            args.protocols,
            "--model-path",
            str(args.model_path),
            "--scaler-path",
            str(args.scaler_path),
            "--alpha",
            str(args.alpha),
            "--gamma",
            str(args.gamma),
            "--mpts-k",
            str(args.mpts_k),
            "--mpts-budget",
            str(args.mpts_budget),
            "--rtt-penalty-weight",
            str(args.rtt_penalty_weight),
            "--iperf-port",
            str(args.iperf_port),
            "--iperf-pad-sec",
            str(args.iperf_pad_sec),
            "--out-dir",
            str(trace_out_dir),
        ]
        if args.skip_mutant:
            sub_cmd.append("--skip-mutant")
        if args.mutant_only:
            sub_cmd.append("--mutant-only")
        if args.run_iperf:
            sub_cmd.append("--run-iperf")
            if args.iperf_target:
                sub_cmd.extend(["--iperf-target", args.iperf_target])

        shell_cmd = "cd {} && {}".format(
            shlex.quote(str(root)),
            " ".join(shlex.quote(x) for x in sub_cmd),
        )

        mm_cmd = [
            "mm-delay",
            str(spec["delay_ms"]),
            "mm-link",
            spec["up_path"],
            spec["down_path"],
            "--uplink-queue",
            args.uplink_queue,
            "--uplink-queue-args",
            args.uplink_queue_args,
            "--downlink-queue",
            args.downlink_queue,
            "--downlink-queue-args",
            args.downlink_queue_args,
            "--",
            "/bin/bash",
            "-lc",
            shell_cmd,
        ]

        print(
            f"[sweep] trace={trace_name} delay_ms={spec['delay_ms']} "
            f"up={Path(spec['up_path']).name} down={Path(spec['down_path']).name} "
            f"steps={per_trace_steps}{f' dur_ms={trace_dur_ms}' if trace_dur_ms else ''}"
        )
        subprocess.run(mm_cmd, check=True)

        trace_summary_csv = trace_out_dir / "summary.csv"
        if not trace_summary_csv.exists():
            raise SystemExit(f"Missing expected summary: {trace_summary_csv}")

        with open(trace_summary_csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                row["trace_name"] = trace_name
                row["trace_up_path"] = spec["up_path"]
                row["trace_down_path"] = spec["down_path"]
                row["trace_delay_ms"] = str(spec["delay_ms"])
                row["trace_out_dir"] = str(trace_out_dir)
                row["trace_duration_steps"] = str(per_trace_steps)
                row["trace_duration_ms"] = trace_dur_ms
                combined_rows.append(row)

    sweep_csv = out_dir / "sweep_summary.csv"
    if combined_rows:
        fieldnames = list(combined_rows[0].keys())
        with open(sweep_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(combined_rows)
        print(f"Sweep complete. Combined summary: {sweep_csv}")
    else:
        print("Sweep complete, but no rows were collected.")


def shutil_which(cmd):
    return shutil.which(cmd) is not None


def build_parser():
    parser = argparse.ArgumentParser(
        description="Run Mutant vs fixed CC algorithms and emit trace CSVs + summary."
    )
    parser.add_argument(
        "--cli-path",
        default="../scripts/protocol_manager_rootns.sh",
        help="Path to protocol manager CLI wrapper.",
    )
    parser.add_argument("--flow-id", type=int, default=1)
    parser.add_argument("--duration-steps", type=int, default=1500)
    parser.add_argument("--step-interval", type=float, default=0.01)
    parser.add_argument("--protocols", default=",".join(DEFAULT_PROTOCOLS))
    parser.add_argument("--skip-mutant", action="store_true")
    parser.add_argument("--mutant-only", action="store_true", help="Run only Mutant (skip fixed CC baselines).")

    parser.add_argument("--model-path", default="../mutant_autoencoder.pth")
    parser.add_argument("--scaler-path", default="../mutant_scaler.save")
    parser.add_argument("--alpha", type=float, default=0.5)
    parser.add_argument("--gamma", type=float, default=0.95)
    parser.add_argument("--mpts-k", type=int, default=6)
    parser.add_argument("--mpts-budget", type=int, default=100)
    parser.add_argument(
        "--rtt-penalty-weight",
        type=float,
        default=0.1,
        help="Reward penalty multiplier for RTT in ms. Higher values bias toward lower-latency protocol choices.",
    )

    parser.add_argument("--run-iperf", action="store_true")
    parser.add_argument("--iperf-target", default=os.environ.get("MAHIMAHI_BASE", ""))
    parser.add_argument("--iperf-port", type=int, default=5201)
    parser.add_argument("--iperf-pad-sec", type=int, default=8)
    parser.add_argument(
        "--python-bin",
        default=sys.executable,
        help="Python interpreter used for nested runs in trace sweep mode.",
    )
    parser.add_argument(
        "--auto-duration",
        action="store_true",
        help="In trace sweep mode, derive duration-steps from each trace length.",
    )
    parser.add_argument(
        "--auto-duration-scale",
        type=float,
        default=1.0,
        help="Multiplier applied to detected trace duration before converting to steps.",
    )
    parser.add_argument(
        "--auto-duration-extra-steps",
        type=int,
        default=0,
        help="Extra steps added on top of auto-computed duration.",
    )
    parser.add_argument(
        "--auto-duration-min-steps",
        type=int,
        default=1,
        help="Minimum steps when auto-duration is enabled.",
    )

    parser.add_argument("--trace-sweep", action="store_true", help="Sweep across multiple Mahimahi traces.")
    parser.add_argument(
        "--traces-dir",
        default="../trcgen/traces",
        help="Trace directory used by --trace-sweep for discovery and relative paths.",
    )
    parser.add_argument(
        "--trace-specs",
        default="",
        help="Semicolon list of trace specs: name,up,down,delay_ms;name2,up2,down2,delay2",
    )
    parser.add_argument(
        "--uplink-queue",
        default="droptail",
        help="Mahimahi uplink queue type for sweep mode.",
    )
    parser.add_argument(
        "--uplink-queue-args",
        default="packets=100",
        help="Mahimahi uplink queue args for sweep mode.",
    )
    parser.add_argument(
        "--downlink-queue",
        default="droptail",
        help="Mahimahi downlink queue type for sweep mode.",
    )
    parser.add_argument(
        "--downlink-queue-args",
        default="packets=100",
        help="Mahimahi downlink queue args for sweep mode.",
    )
    parser.add_argument("--default-delay-ms", type=int, default=50, help="Delay for auto-discovered traces.")
    parser.add_argument(
        "--include-up-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="When auto-discovering, use .up file as both directions if matching .down is absent.",
    )

    parser.add_argument("--_single-run", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--out-dir", default="")
    return parser


def main():
    args = build_parser().parse_args()
    here = Path(__file__).resolve().parent
    root = here.parent

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.trace_sweep and not args._single_run:
        default_name = f"cc_compare_sweep_{timestamp}"
    else:
        default_name = f"cc_compare_{timestamp}"
    out_dir = Path(args.out_dir).resolve() if args.out_dir else (root / "trcgen" / default_name).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.trace_sweep and not args._single_run:
        run_trace_sweep(args, here, root, out_dir)
    else:
        run_single_comparison(args, here, root, out_dir)


if __name__ == "__main__":
    main()
