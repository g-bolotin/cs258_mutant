import math

def generate_trace(filename, duration_ms, bandwidth_func):
    """
    duration_ms: How long the trace lasts.
    bandwidth_func: A function that takes the current time (ms) and returns target Mbps.
    """
    # 1 MTU packet = 1500 bytes = 12,000 bits
    BITS_PER_PACKET = 12000

    with open(filename, 'w') as f:
        current_time_ms = 0.0
        while current_time_ms < duration_ms:
            # Get the target Mbps for this exact millisecond
            current_mbps = bandwidth_func(current_time_ms)

            # Prevent dividing by zero if bandwidth drops to 0
            if current_mbps <= 0:
                current_mbps = 0.1

            # Calculate how many milliseconds it takes to send one packet at this speed
            packets_per_sec = (current_mbps * 1_000_000) / BITS_PER_PACKET
            ms_per_packet = 1000.0 / packets_per_sec

            # Write the timestamp (rounded to nearest ms)
            f.write(f"{int(round(current_time_ms))}\n")

            # Advance time
            current_time_ms += ms_per_packet

    print(f"Generated {filename}")

# --- Trace 1: Flat 2 Mbps (Low Bandwidth) ---
generate_trace("traces/synthetic_2mbps.up", duration_ms=60000, bandwidth_func=lambda t: 2.0)

# --- Trace 2: The "Step" Drop (50 Mbps -> drops to 5 Mbps at 30 seconds) ---
def step_function(t_ms):
    return 50.0 if t_ms < 30000 else 5.0

generate_trace("traces/synthetic_step_drop.up", duration_ms=60000, bandwidth_func=step_function)

# --- Trace 3: Oscillating Bandwidth (Sine wave between 10 Mbps and 40 Mbps) ---
def oscillating_function(t_ms):
    # Completes a full swing every 10 seconds (10000 ms)
    amplitude = 15.0
    baseline = 25.0
    return baseline + amplitude * math.sin((t_ms / 10000.0) * 2 * math.pi)

generate_trace("traces/synthetic_oscillating.up", duration_ms=60000, bandwidth_func=oscillating_function)