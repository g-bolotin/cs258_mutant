##### How to run
You may need to run the following to ensure all protocols are recognized by the kernel:

sudo modprobe -a \
tcp_hybla \
tcp_westwood \
tcp_veno \
tcp_vegas \
tcp_yeah \
tcp_bic \
tcp_htcp \
tcp_highspeed \
tcp_illinois \
tcp_bbr

Compile protocol_manager if needed (provided already):
- gcc csrc/protocol_manager.c csrc/cli.c -o protocol_manager

First ensure that you have the pretrained autoencoder. If you need data, unzip master_collected_traces.zip and
run gen_data.py. Then run train_autoenc.py.

To ensure MahiMahi works:
- sudo sysctl -w net.ipv4.ip_forward=1

Then initialize a Mahimahi shell. 
For example, to test mm-loss: 
- mm-delay 50 mm-loss uplink 0.05

Or, to test mm-link: 
- mm-link 12mbps.trace 12mbps.trace
- Made with seq 1 60000 > 12mbps.trace
- 12 Mbps trace (1 packet per millisecond for 60 seconds)

If you find that it over-relies on Hypla and has huge bufferbloat bc of the near-infinite buffer size, try limiting packet amount:
- mm-link 12mbps.trace 12mbps.trace --uplink-queue="droptail" --uplink-queue-args="packets=100"

In another terminal window, run an iperf3 server:
- iperf3 -s

In the Mahimahi window, run iperf3 for simulated traffic (300s):
- iperf3 -c $MAHIMAHI_BASE -t 300 > iperf.log &

The ampersand will ensure it runs in the background, also creates a log.
Bring it to foreground to kill it if needed using fg
MAHIMAHI_BASE variable represents IP of the host machine (where we're running our iperf3 server).

In the same Mahimahi window, run the Python RL runner:
(assuming you're in cs258_mutant as the CWD)
- sudo python3 python/rl_runner.py

If you're running in a virtual environment, you might need this instead:
- sudo .venv/bin/python python/rl_runner.py

This will output results to console (server), iperf3.log (client), and also to a CSV file pertaining to the protocol used.

To exit, bring iperf3 to foreground with fg and ctrl-c, then exit the Mahimahi process and terminate the server on the other window.
