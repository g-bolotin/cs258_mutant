#!/bin/bash

# Clear out any old master file so we start fresh
rm -f master_collected_traces.csv
echo "Starting automated data collection..."

TRACES=(
    "./traces/Verizon-LTE-short.up"
    "./traces/TMobile-UMTS-driving.down"
    "./traces/ATT-LTE-driving.up"
    "./traces/ATT-LTE-driving.down"
    "./traces/synthetic_2mbps.up"
    "./traces/synthetic_step_drop.up"
    "./traces/synthetic_oscillating.up"
)

for trace in "${TRACES[@]}"; do
    echo "====================================================="
    echo "Spinning up Mahimahi link with trace: $trace"
    echo "====================================================="

    # Symmetric up and downlink instead of paired .up and .down
    # Not the most realistic but less noise
    mm-link "$trace" "$trace" -- python3 "../python/gen_data.py"

    echo "Finished trace: $trace"
    sleep 2 # let sockets completely clear
done

echo "====================================================="
echo "All environments complete! Data saved to master_collected_traces.csv"