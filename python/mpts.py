import math
import time
from reward import compute_reward

def run_mpts(env, protocols, target_k=6, T=100, step_interval=0.01, rtt_penalty_weight=0.1):
    print(f"--- Running MPTS (Mutant Protocol Team Selection) ---")
    print(f"Target Team Size (k): {target_k}, Total Budget (T): {T}")

    n = len(protocols)
    if target_k >= n:
        return list(protocols)

    # Calculate log_bar_T to distribute the sampling budget T
    log_bar_T = 0.5 + sum(1.0 / i for i in range(2, T + 1))

    n_j = [0] * n
    for j in range(1, n):
        val = (1.0 / log_bar_T) * ((T - n) / (n + 1 - j))
        n_j[j] = math.ceil(val)

    active_arms = list(protocols)
    accepted_arms = []

    total_reward = {p: 0.0 for p in protocols}
    pulls = {p: 0 for p in protocols}
    k_j = target_k

    # Run selection phases 1 to n-1
    for j in range(1, n):
        pulls_this_phase = max(0, n_j[j] - n_j[j-1])

        # 1. Select each active arm n_j - n_{j-1} times
        for _ in range(pulls_this_phase):
            for p in active_arms:
                env.set_protocol(p)
                time.sleep(step_interval)
                metrics = env.get_metrics()
                if metrics:
                    r = compute_reward(metrics, rtt_penalty_weight=rtt_penalty_weight)
                    total_reward[p] += r
                pulls[p] += 1

        # Calculate empirical means for active protocols
        empirical_means = {}
        for p in active_arms:
            empirical_means[p] = total_reward[p] / pulls[p] if pulls[p] > 0 else 0.0

        # 2. Sort current active empirical means in descending order
        sorted_arms = sorted(active_arms, key=lambda p: empirical_means[p], reverse=True)

        # 3. Compute empirical gaps
        gaps = {}
        for r_idx in range(len(sorted_arms)):
            r = r_idx + 1 # 1-based index
            p_r = sorted_arms[r_idx]

            # Fast-track: if target k >= remaining active pool, force process
            if k_j >= len(sorted_arms):
                gaps[p_r] = float('inf')
                continue

            if r <= k_j:
                mu_k_plus_1 = empirical_means[sorted_arms[k_j]] # k_j is the (k_j+1)-th element
                gaps[p_r] = empirical_means[p_r] - mu_k_plus_1
            else:
                mu_k = empirical_means[sorted_arms[k_j - 1]]    # k_j-1 is the k_j-th element
                gaps[p_r] = mu_k - empirical_means[p_r]

        # 4. Deactivate the arm that maximizes the empirical distance gap
        i_j = max(active_arms, key=lambda p: gaps[p])
        active_arms.remove(i_j)

        # 5. Determine if we accept or reject the deactivated protocol
        if k_j > 0:
            if k_j < len(sorted_arms):
                mu_k_plus_1 = empirical_means[sorted_arms[k_j]]
                if empirical_means[i_j] > mu_k_plus_1:
                    accepted_arms.append(i_j)
                    k_j -= 1
            else:
                # Need more arms than available, safely accept
                accepted_arms.append(i_j)
                k_j -= 1

    # Exhausted phases. Check if the single remaining arm should complete our k threshold
    if k_j > 0 and len(active_arms) > 0:
        accepted_arms.extend(active_arms[:k_j])

    final_team = accepted_arms[:target_k]
    print(f"MPTS Selected Coalition: {final_team}")
    return final_team