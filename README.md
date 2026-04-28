##### How to run
You may need to run the following to ensure all protocols are recognized by the kernel:

sudo modprobe tcp_hybla
sudo modprobe tcp_westwood
sudo modprobe tcp_veno
sudo modprobe tcp_vegas
sudo modprobe tcp_yeah
sudo modprobe tcp_bic
sudo modprobe tcp_htcp
sudo modprobe tcp_highspeed
sudo modprobe tcp_illinois
sudo modprobe tcp_bbr

Compile protocol_manager:
- gcc csrc/protocol_manager.c csrc/cli.c -o protocol_manager

To ensure MahiMahi works:
- sudo sysctl -w net.ipv4.ip_forward=1

Then initialize a Mahimahi shell. 
For example, to test mm-loss: 
- mm-delay 50 mm-loss uplink 0.05

Or, to test mm-link: 
- mm-link 12mbps.trace 12mbps.trace
- Made with seq 1 60000 > 12mbps.trace
- 12 Mbps trace (1 packet per millisecond for 60 seconds)

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
