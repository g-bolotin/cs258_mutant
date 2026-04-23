import time
import csv
from env import MutantEnv


def run_static_baseline(env, protocol, duration_steps=20, step_interval=0.5):
    """
    Runs a flow using a single, static protocol and logs the metrics.
    This acts as a baseline comparison for the RL agent later.
    """
    print(f"--- Starting Baseline Run: {protocol.upper()} ---")

    # 1. Reset environment and set the target protocol
    env.reset(initial_protocol=protocol)

    # 2. Prepare logging (saving metrics per step)
    log_filename = f"baseline_{protocol}_{int(time.time())}.csv"

    with open(log_filename, mode='w', newline='') as file:
        writer = None

        # 3. The Automation Loop
        for step in range(duration_steps):
            metrics = env.get_metrics()

            if metrics:
                # Initialize CSV headers dynamically on the first step
                if writer is None:
                    writer = csv.DictWriter(file, fieldnames=["step"] + list(metrics.keys()))
                    writer.writeheader()

                # Write the row
                row_data = {"step": step}
                row_data.update(metrics)
                writer.writerow(row_data)

                print(f"Step {step:02d} | RTT: {metrics['rtt_ms']:6.2f}ms | "
                      f"Throughput: {metrics['throughput_mbps']:6.2f}Mbps | "
                      f"Loss: {metrics['loss']}")

            time.sleep(step_interval)

    print(f"Run complete. Data saved to {log_filename}\n")


if __name__ == "__main__":
    # Make sure the path points to where you compiled protocol_manager
    env = MutantEnv(cli_path="./protocol_manager", flow_id=1)

    # Run a quick baseline test for Cubic
    run_static_baseline(env, protocol="cubic", duration_steps=10)

    # Run a quick baseline test for BBR
    run_static_baseline(env, protocol="bbr", duration_steps=10)