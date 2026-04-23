import subprocess
import json
import time

class MutantEnv:
    def __init__(self, cli_path="../protocol_manager", flow_id=1):
        self.cli_path = cli_path
        self.flow_id = flow_id

    def set_protocol(self, protocol_name):
        """Commands the C binary to switch the protocol."""
        subprocess.run(
            [self.cli_path, "--flow", str(self.flow_id), "--set", protocol_name],
            stdout=subprocess.DEVNULL, # Hide the C print statements
            stderr=subprocess.DEVNULL
        )

    def get_metrics(self):
        """Calls the C binary to read metrics and parses the JSON output."""
        result = subprocess.run(
            [self.cli_path, "--flow", str(self.flow_id), "--read-metrics"],
            capture_output=True,
            text=True
        )
        try:
            # Parse the JSON string printed by the C program
            return json.loads(result.stdout.strip())
        except json.JSONDecodeError:
            print(f"Error parsing metrics from C binary: {result.stdout}")
            return None

    def reset(self, initial_protocol="cubic"):
        """Resets the environment for a new run."""
        self.set_protocol(initial_protocol)
        time.sleep(0.1) # Give the kernel a fraction of a second to settle
        return self.get_metrics()