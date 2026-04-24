import random
import numpy as np

class MutantLearner:
    def __init__(self, protocols, epsilon=0.2):
        self.protocols = protocols
        self.epsilon = epsilon

        # Simple Q-table to track the expected reward for each protocol
        # Format: { 'cubic': 0.0, 'bbr': 0.0, 'vegas': 0.0 }
        self.q_values = {p: 0.0 for p in protocols}
        self.action_counts = {p: 0 for p in protocols}

    def preprocess_state(self, metrics):
        """
        Converts the raw JSON metrics into a state vector for the RL model.
        (For a simple bandit, we don't need this yet, but you'll need it for full RL).
        """
        # Example normalized state: [RTT, Throughput, CWND]
        return np.array([
            metrics['rtt_ms'] / 100.0,         # Normalize against 100ms
            metrics['throughput_mbps'] / 50.0, # Normalize against 50Mbps
            metrics['cwnd'] / 1000.0           # Normalize against 1000 packets
        ])

    def select_action(self, state_vector):
        """Epsilon-Greedy action selection."""
        # Explore: pick a random protocol
        if random.random() < self.epsilon:
            return random.choice(self.protocols)

        # Exploit: pick the protocol with the highest historical reward
        best_protocol = max(self.q_values, key=self.q_values.get)
        return best_protocol

    def update(self, action, reward):
        """Updates the Q-value for the chosen action using a running average."""
        self.action_counts[action] += 1
        n = self.action_counts[action]

        # Incremental average update formula
        current_q = self.q_values[action]
        self.q_values[action] = current_q + (1.0 / n) * (reward - current_q)