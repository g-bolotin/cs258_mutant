import time
import csv
import random
import os
import subprocess
from env import MutantEnv
from rl_runner import NetworkHistory

def get_feature_headers(base_keys, temporal_keys):
    headers = list(base_keys)
    for window in ['short', 'med', 'long']:
        for stat in ['min', 'max', 'mean']:
            for key in temporal_keys:
                headers.append(f"{key}_{stat}_{window}")
    return headers

def collect_training_data(env, duration_steps=5000, step_interval=0.01):
    print("--- Starting Offline Data Collection ---")

    env.reset(initial_protocol="cubic")
    log_filename = "master_collected_traces.csv"

    protocol_pool = ["cubic", "hybla", "bbr", "westwood", "veno", "vegas", "yeah", "bic", "htcp", "highspeed", "illinois"]

    base_keys = [
        'cwnd', 'rtt_ms', 'smoothed_rtt', 'mdev_us', 'min_rtt',
        'advmss', 'delivered', 'lost_out', 'in_flight', 'retrans_out',
        'delivery_rate', 'throughput_mbps', 'loss', 'prev_proto', 'crt_proto'
    ]
    temporal_keys = ['rtt_ms', 'throughput_mbps', 'cwnd', 'delivery_rate']

    history = NetworkHistory(track_keys=temporal_keys)
    feature_headers = get_feature_headers(base_keys, temporal_keys)
    csv_headers = ["step", "action_taken"] + feature_headers

    current_action = "cubic"
    file_exists = os.path.isfile(log_filename)

    print("Spinning up iperf3 traffic generator...")

    # Start the client sending traffic to Mahimahi's default host IP
    # We calculate the time so the transfer lasts just slightly longer than our loop
    duration_secs = int(duration_steps * step_interval) + 5
    client_proc = subprocess.Popen(
        ['iperf3', '-c', '10.0.0.1', '-t', str(duration_secs)]
    )
    time.sleep(1.0) # Give the TCP handshake a second to finish and ramp up

    print("Traffic flowing. Collecting metrics...")

    try:
        with open(log_filename, mode='a', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=csv_headers)
            if not file_exists:
                writer.writeheader()

            for step in range(duration_steps):
                if step % 50 == 0:
                    current_action = random.choice(protocol_pool)
                    env.set_protocol(current_action)

                time.sleep(step_interval)

                metrics = env.get_metrics()

                # If metrics are empty or failing, skip to next step
                if not metrics:
                    continue

                history.update(metrics)
                base_features = [metrics.get(k, 0.0) for k in base_keys]
                temporal_features = history.get_temporal_features()

                raw_features = base_features + temporal_features

                row_data = dict(zip(feature_headers, raw_features))
                row_data["step"] = step
                row_data["action_taken"] = current_action

                writer.writerow(row_data)

                if step > 0 and step % 500 == 0:
                    print(f"Collected {step}/{duration_steps} steps... (Current: {current_action.upper()})")

    finally:
        print("Cleaning up iperf3 processes...")
        client_proc.terminate()
        client_proc.wait()

    print(f"Data collection complete! Saved to {log_filename}")

if __name__ == "__main__":
    env = MutantEnv(cli_path="../protocol_manager", flow_id=1)
    collect_training_data(env, duration_steps=5000, step_interval=0.01)