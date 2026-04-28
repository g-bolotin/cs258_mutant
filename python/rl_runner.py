import time
import csv
import torch
import numpy as np
from env import MutantEnv
from reward import compute_reward
from encoder import MutantEncoder
from learner import LinUCBAgent
from collections import deque

class NetworkHistory:
    def __init__(self, track_keys):
        self.track_keys = track_keys
        # Initialize sliding windows with max lengths from the paper
        self.short_win = deque(maxlen=10)
        self.med_win = deque(maxlen=200)
        self.long_win = deque(maxlen=1000)

    def update(self, metrics):
        """Pulls the specific keys we want to track and adds them to the windows."""
        current_vals = [metrics.get(k, 0.0) for k in self.track_keys]
        self.short_win.append(current_vals)
        self.med_win.append(current_vals)
        self.long_win.append(current_vals)

    def get_temporal_features(self):
        """Calculates Min, Max, and Mean for each window."""
        temporal_features = []

        # If no data yet, return an array of zeros
        if not self.short_win:
            num_stats = len(self.track_keys) * 3 * 3  # (keys * [min, max, mean] * 3 windows)
            return [0.0] * num_stats

        # Calculate stats for all three windows
        for window in [self.short_win, self.med_win, self.long_win]:
            # Convert deque to numpy array for fast column-wise math
            arr = np.array(window)

            mins = np.min(arr, axis=0)
            maxs = np.max(arr, axis=0)
            means = np.mean(arr, axis=0)

            # Extend the feature list
            temporal_features.extend(mins.tolist() + maxs.tolist() + means.tolist())

        return temporal_features

def run_rl_experiment(env, encoder, agent, duration_steps=60, step_interval=0.01):
    print("--- Starting Mutant RL Training Run (LinUCB) ---")

    # Initialize the network
    env.reset(initial_protocol="cubic")
    log_filename = f"rl_training_{int(time.time())}.csv"

    with open(log_filename, mode='w', newline='') as file:
        writer = None

        # The 15 base features we want to pull directly from the current step
        base_keys = [
            'cwnd', 'rtt_ms', 'smoothed_rtt', 'mdev_us', 'min_rtt',
            'advmss', 'delivered', 'lost_out', 'in_flight', 'retrans_out',
            'delivery_rate', 'throughput_mbps', 'loss', 'prev_proto', 'crt_proto'
        ]

        # The subset we want to track temporally (Mean, Min, Max)
        # 4 keys * 3 stats * 3 windows = 36 temporal features
        temporal_keys = ['rtt_ms', 'throughput_mbps', 'cwnd', 'delivery_rate']
        history = NetworkHistory(track_keys=temporal_keys)

        for step in range(duration_steps):
            # 1. Observe current state
            metrics = env.get_metrics()
            if not metrics:
                continue

            # Update our sliding windows with the new data
            history.update(metrics)

            # Extract the 15 base features
            base_features = [metrics.get(k, 0.0) for k in base_keys]

            # Calculate the 36 temporal features (Min, Max, Mean across windows)
            temporal_features = history.get_temporal_features()

            # Combine them (15 + 36 = 51 features)
            raw_features = base_features + temporal_features

            # Pad the last 4 dimensions to perfectly match the 55-dimension PyTorch Encoder
            # (The paper likely tracked one more metric, but padding 4 zeros won't hurt the GRU)
            raw_features += [0.0] * (55 - len(raw_features))

            # Format as a PyTorch tensor: (batch=1, seq_len=1, features=55)
            state_tensor = torch.FloatTensor(raw_features).unsqueeze(0).unsqueeze(0)

            # 2. Encode state
            with torch.no_grad():
                latent_tensor = encoder(state_tensor)
                # Convert the 16-dim tensor back to a standard numpy array for LinUCB
                z_t = latent_tensor.numpy().flatten()

                # 3. Choose action using Contextual MAB
            action = agent.select_action(z_t)

            # 4. Apply action
            env.set_protocol(action)

            # 5. Wait for network
            # Switching interval defined by Pappone et al. paper, delta = 10^-2 seconds
            time.sleep(step_interval)

            # 6. Observe new state, calculate reward
            new_metrics = env.get_metrics()
            if not new_metrics:
                continue

            reward = compute_reward(new_metrics, rtt_penalty_weight=0.1)

            # 7. Update learner
            agent.update(action, z_t, reward)

            # --- Logging ---
            if writer is None:
                fieldnames = ["step", "action_taken", "reward"] + list(new_metrics.keys())
                writer = csv.DictWriter(file, fieldnames=fieldnames)
                writer.writeheader()

            row_data = {"step": step, "action_taken": action, "reward": round(reward, 2)}
            row_data.update(new_metrics)
            writer.writerow(row_data)

            print(f"Step {step:02d} | Action: {action.upper():<5} | "
                  f"Reward: {reward:6.2f} | RTT: {new_metrics['rtt_ms']:6.2f}ms | "
                  f"TP: {new_metrics['throughput_mbps']:5.2f}Mbps")

    print(f"\nRun complete. Data saved to {log_filename}")

if __name__ == "__main__":
    env = MutantEnv(cli_path="./protocol_manager", flow_id=1)
    protocol_pool = ["cubic", "bbr", "vegas"]

    # Instantiate the new PyTorch Encoder
    encoder = MutantEncoder()
    encoder.eval()

    # Instantiate the Contextual MAB Agent
    agent = LinUCBAgent(protocol_pool, latent_dim=16, alpha=0.5)

    run_rl_experiment(env, encoder, agent, duration_steps=3000, step_interval=0.01)