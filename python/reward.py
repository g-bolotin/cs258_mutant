def compute_reward(metrics, rtt_penalty_weight=0.1):
    """
    Calculates the reward for the RL agent.
    Goal: Maximize throughput while minimizing RTT.
    """
    throughput = metrics.get('throughput_mbps', 0.0)
    rtt = metrics.get('rtt_ms', 0.0)

    # Reward = Throughput - (Penalty * RTT)
    # The penalty weight controls how aggressively the agent avoids high latency
    reward = throughput - (rtt_penalty_weight * rtt)

    return reward