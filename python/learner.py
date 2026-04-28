import numpy as np

class LinUCBAgent:
    def __init__(self, protocols, latent_dim=16, alpha=0.5, gamma=0.95):
        """
        alpha: Controls the exploration-exploitation trade-off.
               Higher alpha = more exploration.
        """
        self.protocols = protocols
        self.n_arms = len(protocols)
        self.d = latent_dim
        self.alpha = alpha
        self.gamma = gamma # Forgetting factor

        # Initialize A matrix (d x d identity matrix) and b vector (d x 1 zero vector) for each protocol
        self.A = {p: np.identity(self.d) for p in protocols}
        self.b = {p: np.zeros((self.d, 1)) for p in protocols}
        self.action_counts = {p: 0 for p in protocols}

    def select_action(self, z_t):
        """
        z_t: The 16-dimensional latent vector from the PyTorch encoder (numpy array).
        """
        for p in self.protocols:
            if self.action_counts[p] == 0:
                return p

        z_t = z_t.reshape((self.d, 1))
        p_values = {}

        for p in self.protocols:
            # Calculate A inverse
            A_inv = np.linalg.inv(self.A[p])

            # Estimate weights theta
            theta = A_inv @ self.b[p]

            # Expected reward estimate: theta^T * z_t
            expected_reward = theta.T @ z_t

            # Confidence interval (uncertainty)
            confidence_interval = self.alpha * np.sqrt(z_t.T @ A_inv @ z_t)

            # UCB score
            p_values[p] = (expected_reward + confidence_interval)[0][0]

        # Select the protocol with the highest UCB score
        best_protocol = max(p_values, key=p_values.get)
        return best_protocol

    def update(self, action, z_t, reward):
        """
        Updates the A matrix and b vector for the chosen protocol.
        """
        self.action_counts[action] += 1
        z_t = z_t.reshape((self.d, 1))

        # Online update equations for Bayesian linear regression
        self.A[action] = (self.A[action] * self.gamma) + (z_t @ z_t.T)
        self.b[action] = (self.b[action] * self.gamma) + (reward * z_t)