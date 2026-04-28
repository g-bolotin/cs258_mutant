import subprocess
import json

class MutantEnv:
    def __init__(self, cli_path="./protocol_manager", flow_id=1):
        self.cli_path = cli_path
        self.flow_id = flow_id

    def get_metrics(self):
        """
        Executes the compiled C binary, captures its JSON output,
        and converts it into a Python dictionary.
        """
        try:
            # UPDATED: Pass the exact flags the C binary expects
            result = subprocess.run(
                [self.cli_path, "--flow", str(self.flow_id), "--read-metrics"],
                capture_output=True,
                text=True,
                timeout=2
            )

            if result.stdout:
                # The C code should be printing a valid JSON string
                metrics = json.loads(result.stdout.strip())
                return metrics

        except json.JSONDecodeError:
            print(f"JSON Parsing Error. Raw C output: {result.stdout}")
        except Exception as e:
            print(f"Error reading from C module: {e}")

        return None

    def set_protocol(self, protocol_name):
        """
        Commands the custom C binary to hot-swap the tcp_congestion_ops struct
        for the active flow, bypassing sysctl and Mahimahi namespace restrictions.
        """
        try:
            result = subprocess.run(
                [self.cli_path, "--flow", str(self.flow_id), "--set", protocol_name],
                check=True,
                capture_output=True,
                text=True
            )
        except subprocess.CalledProcessError as e:
            print(f"ERROR: C binary rejected protocol '{protocol_name}'.")
            print(f"Command Output: {e.stderr or e.stdout}")

    def reset(self, initial_protocol="cubic"):
        """Resets the environment back to a safe default baseline."""
        self.set_protocol(initial_protocol)