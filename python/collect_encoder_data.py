import argparse
import csv
import os
import random
import subprocess
import time
from collections import deque

from env import MutantEnv


class NetworkHistory:
    def __init__(self, track_keys):
        self.track_keys = track_keys
        self.short_win = deque(maxlen=10)
        self.med_win = deque(maxlen=200)
        self.long_win = deque(maxlen=1000)

    def update(self, metrics):
        current_vals = [metrics.get(k, 0.0) for k in self.track_keys]
        self.short_win.append(current_vals)
        self.med_win.append(current_vals)
        self.long_win.append(current_vals)

    def get_temporal_features(self):
        temporal_features = []

        if not self.short_win:
            return [0.0] * (len(self.track_keys) * 3 * 3)

        for window in [self.short_win, self.med_win, self.long_win]:
            rows = list(window)
            cols = list(zip(*rows))
            mins = [min(col) for col in cols]
            maxs = [max(col) for col in cols]
            means = [sum(col) / len(col) for col in cols]
            temporal_features.extend(mins + maxs + means)

        return temporal_features


def get_feature_headers(base_keys, temporal_keys):
    headers = list(base_keys)
    for window in ["short", "med", "long"]:
        for stat in ["min", "max", "mean"]:
            for key in temporal_keys:
                headers.append(f"{key}_{stat}_{window}")
    return headers


def maybe_switch_protocol(env, current_protocol, protocol_pool, switch_probability):
    if random.random() >= switch_probability:
        return current_protocol, False

    candidates = [p for p in protocol_pool if p != current_protocol]
    if not candidates:
        return current_protocol, False

    next_protocol = random.choice(candidates)
    env.set_protocol(next_protocol)
    return next_protocol, True


def collect_training_data(args):
    protocol_pool = [
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
        "cdg",
    ]
    # Paper-aligned feature layout (55):
    # - 10 raw (non-bold Table-1 fields)
    # - 5 bold fields expanded across 3 windows x (min,max,mean) = 45
    base_keys = [
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
    temporal_keys = [
        "smoothed_rtt",
        "mdev_us",
        "lost_out",
        "in_flight",
        "throughput_mbps",
    ]
    history = NetworkHistory(track_keys=temporal_keys)
    feature_headers = get_feature_headers(base_keys, temporal_keys)
    csv_headers = ["step", "action_taken"] + feature_headers

    env = MutantEnv(cli_path=args.cli_path, flow_id=args.flow_id)
    env.reset(initial_protocol=args.initial_protocol)
    current_protocol = args.initial_protocol

    output_dir = os.path.dirname(os.path.abspath(args.output))
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    file_exists = os.path.isfile(args.output)

    iperf_proc = None
    iperf_seconds = int(args.duration_steps * args.step_interval) + args.iperf_pad_sec

    if args.run_iperf:
        iperf_cmd = ["iperf3", "-c", args.iperf_target, "-t", str(iperf_seconds)]
        iperf_proc = subprocess.Popen(iperf_cmd)
        time.sleep(1.0)

    switch_count = 0
    recv_count = 0
    idle_steps = 0
    next_switch_time = time.monotonic() + args.switch_interval_sec

    print("--- Collecting encoder training data ---")
    print(f"Output CSV: {args.output}")
    print(
        f"Switch policy: every {args.switch_interval_sec:.3f}s with "
        f"{args.switch_probability * 100:.0f}% switch probability"
    )

    try:
        with open(args.output, mode="a", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=csv_headers)
            if not file_exists:
                writer.writeheader()

            for step in range(args.duration_steps):
                if iperf_proc is not None and args.stop_on_iperf_exit and iperf_proc.poll() is not None:
                    print(f"[stop] iperf3 exited (code={iperf_proc.returncode}) at step={step}")
                    break

                now = time.monotonic()
                while now >= next_switch_time:
                    current_protocol, switched = maybe_switch_protocol(
                        env, current_protocol, protocol_pool, args.switch_probability
                    )
                    if switched:
                        switch_count += 1
                        print(f"[switch] step={step} protocol={current_protocol}")
                    next_switch_time += args.switch_interval_sec

                metrics = env.get_metrics()
                if metrics:
                    throughput = float(metrics.get("throughput_mbps", 0.0))
                    history.update(metrics)
                    base_features = [metrics.get(k, 0.0) for k in base_keys]
                    temporal_features = history.get_temporal_features()
                    raw_features = base_features + temporal_features

                    row_data = dict(zip(feature_headers, raw_features))
                    row_data["step"] = step
                    row_data["action_taken"] = current_protocol
                    writer.writerow(row_data)
                    recv_count += 1
                    if throughput > 0.0:
                        idle_steps = 0
                    else:
                        idle_steps += 1
                else:
                    idle_steps += 1

                if args.max_idle_steps > 0 and idle_steps >= args.max_idle_steps:
                    print(
                        f"[stop] no useful traffic for {idle_steps} steps "
                        f"(max_idle_steps={args.max_idle_steps}) at step={step}"
                    )
                    break

                if step % args.progress_every == 0 and step > 0:
                    print(
                        f"[progress] step={step}/{args.duration_steps} "
                        f"rows={recv_count} switches={switch_count} current={current_protocol}"
                    )

                time.sleep(args.step_interval)

    finally:
        if iperf_proc is not None:
            iperf_proc.terminate()
            iperf_proc.wait()

    print(
        f"Done. steps={args.duration_steps} rows={recv_count} "
        f"switches={switch_count} output={args.output}"
    )


def build_parser():
    parser = argparse.ArgumentParser(description="Collect Mutant encoder data via Mahimahi + iperf.")
    parser.add_argument("--cli-path", default="../protocol_manager", help="Path to protocol_manager binary.")
    parser.add_argument("--flow-id", type=int, default=1, help="Flow ID passed to protocol_manager.")
    parser.add_argument("--output", default="../trcgen/master_collected_traces_v55.csv", help="Output CSV path.")
    parser.add_argument("--duration-steps", type=int, default=5000, help="Number of sampling steps.")
    parser.add_argument("--step-interval", type=float, default=0.01, help="Seconds between samples.")
    parser.add_argument(
        "--switch-interval-sec",
        type=float,
        default=0.5,
        help="Time interval between switch decisions in seconds.",
    )
    parser.add_argument(
        "--switch-probability",
        type=float,
        default=0.5,
        help="Probability of switching protocol at each switch decision.",
    )
    parser.add_argument(
        "--initial-protocol",
        default="cubic",
        choices=["cubic", "hybla", "bbr", "westwood", "veno", "vegas", "yeah", "bic", "htcp", "illinois", "cdg"],
        help="Initial congestion control protocol.",
    )
    parser.add_argument("--progress-every", type=int, default=500, help="Progress log frequency in steps.")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed for reproducible switching.")
    parser.add_argument("--run-iperf", action="store_true", help="Start iperf3 client automatically.")
    parser.add_argument("--iperf-target", default="10.0.0.1", help="iperf3 server target IP/host.")
    parser.add_argument("--iperf-pad-sec", type=int, default=8, help="Extra seconds added to iperf runtime.")
    parser.add_argument(
        "--stop-on-iperf-exit",
        action="store_true",
        default=True,
        help="Stop collection as soon as iperf3 exits (default: enabled).",
    )
    parser.add_argument(
        "--no-stop-on-iperf-exit",
        dest="stop_on_iperf_exit",
        action="store_false",
        help="Keep collecting even after iperf3 exits.",
    )
    parser.add_argument(
        "--max-idle-steps",
        type=int,
        default=400,
        help="Stop if throughput stays zero or metrics fail for this many consecutive steps (0 disables).",
    )
    return parser


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    random.seed(args.seed)
    collect_training_data(args)
