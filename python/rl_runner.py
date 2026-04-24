import time
import csv
from env import MutantEnv
from learner import MutantLearner
from reward import compute_reward

def run_rl_experiment(env, learner, duration_steps=60, step_interval=0.5):
    print("--- Starting Mutant RL Training Run ---")

    # Initialize the network with a safe default
    env.reset(initial_protocol="cubic")

    log_filename = f"rl_training_{int(time.time())}.csv"

    with open(log_filename, mode='w', newline='') as file:
        writer = None

        for step in range(duration_steps):
            # 1. OBSERVE CURRENT STATE
            metrics = env.get_metrics()
            if not metrics:
                continue

            state_vector = learner.preprocess_state(metrics)

            # 2. CHOOSE ACTION
            action = learner.select_action(state_vector)

            # 3. APPLY ACTION
            env.set_protocol(action)

            # 4. WAIT FOR NETWORK TO REACT
            # The agent needs time to see how its choice impacted the traffic
            time.sleep(step_interval)

            # 5. OBSERVE NEW STATE
            new_metrics = env.get_metrics()
            if not new_metrics:
                continue

            # 6. CALCULATE REWARD
            # Did the action we just took increase throughput and lower RTT?
            reward = compute_reward(new_metrics, rtt_penalty_weight=0.1)

            # 7. UPDATE LEARNER
            # Teach the agent if that was a good or bad decision
            learner.update(action, reward)

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
    print("\nFinal Learned Q-Values:")
    for proto, val in learner.q_values.items():
        print(f"  {proto.upper()}: {val:.2f}")

if __name__ == "__main__":
    # Ensure the path points to your compiled C binary
    env = MutantEnv(cli_path="./protocol_manager", flow_id=1)

    protocol_pool = ["cubic", "bbr", "vegas"]

    # Initialize the learner with an epsilon of 0.3 (30% exploration rate)
    agent = MutantLearner(protocol_pool, epsilon=0.3)

    # Run for 60 steps to give it time to explore and learn
    run_rl_experiment(env, agent, duration_steps=60)