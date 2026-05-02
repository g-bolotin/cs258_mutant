import os
import time
import csv
import torch
import numpy as np
from env import MutantEnv
from reward import compute_reward
from autoencoder import MutantAutoencoder
from learner import LinUCBAgent
from collections import deque
import joblib
from mpts import run_mpts

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

def run_rl_experiment(env, encoder, agent, scaler, duration_steps=60, step_interval=0.01):
    print("--- Starting Mutant RL Training Run (LinUCB) ---")

    # Initialize the network
    env.reset(initial_protocol="cubic")
    log_filename = f"rl_training_{int(time.time())}.csv"

    # Paper-aligned 55-dim state:
    # 10 raw non-bold metrics + 45 temporal stats from 5 bold metrics.
    base_keys = [
        'cwnd', 'rtt_ms', 'min_rtt', 'advmss', 'delivered',
        'retrans_out', 'delivery_rate', 'prev_proto', 'crt_proto', 'loss_rate'
    ]

    # 5 keys * 3 stats * 3 windows = 45 temporal features
    temporal_keys = ['smoothed_rtt', 'mdev_us', 'lost_out', 'in_flight', 'throughput_mbps']
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

        # Combine them (10 + 45 = 55 features)
        raw_features = base_features + temporal_features

        # Reshape to 2D for the scaler, then back to 1D
        scaled_features = scaler.transform([raw_features])[0]

        # Format as a PyTorch tensor: (batch=1, seq_len=1, features=55)
        state_tensor = torch.FloatTensor(scaled_features).unsqueeze(0).unsqueeze(0)

        # 2. Encode state
        with torch.no_grad():
            latent_tensor = model.encode(state_tensor)
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

        throughput = new_metrics.get('throughput_mbps', 0.0)
        rtt = new_metrics.get('rtt_ms', 0.0)

        reward = compute_reward(new_metrics, rtt_penalty_weight=0.1)

        # 7. Update learner
        agent.update(action, z_t, reward)

        print(f"Step {step:02d} | Action: {action.upper():<10} | Reward: {reward:6.2f} | RTT: {rtt:6.2f}ms | TP: {throughput:5.2f}Mbps")

if __name__ == "__main__":
    env = MutantEnv(cli_path="./protocol_manager", flow_id=1)
    protocol_pool = ["cubic", "hybla", "bbr", "westwood", "veno", "vegas", "yeah", "bic", "htcp", "highspeed", "illinois"]

    # 1. Run MPTS to extract the top K=6 protocols (T=100) before RL loop starts
    # Using defaults mentioned in Pappone et al. (Section 6.1 / 6.3)
    selected_protocols = run_mpts(env, protocol_pool, target_k=6, T=100, step_interval=0.01)

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

    model_path = os.path.join(BASE_DIR, '../mutant_autoencoder.pth')
    scaler_path = os.path.join(BASE_DIR, '../mutant_scaler.save')

    print(f"Looking for model at: {model_path}")

    # Instantiate Autoencoder
    model = MutantAutoencoder(input_dim=55)
    model.load_state_dict(torch.load(model_path))
    scaler = joblib.load(scaler_path)

    # Instantiate the Contextual MAB Agent
    agent = LinUCBAgent(selected_protocols, latent_dim=16, alpha=0.5)

    run_rl_experiment(env, model, agent, scaler, duration_steps=3000, step_interval=0.01)
