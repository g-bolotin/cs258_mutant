Compile protocol_manager:
gcc csrc/protocol_manager.c csrc/cli.c -o protocol_manager

Run: sudo sysctl -w net.ipv4.ip_forward=1

Then initialize a Mahimahi shell, for example:
mm-delay 50 mm-loss uplink 0.05

In another terminal window, run an iperf3 server:
iperf3 -s

In the Mahimahi window, run iperf3 for simulated traffic (60s):
iperf3 -c $MAHIMAHI_BASE -t 60 > /dev/null 2>&1 &

The ampersand will ensure it runs in the background. 
Bring it to foreground to kill it if needed using fg
MAHIMAHI_BASE variable represents IP of the host machine (where we're running our iperf3 server).

In the same Mahimahi window, run the Python runner:
sudo python3 python/runner.py
(assuming you're in cs258_mutant as the CWD)

This will output results to console and also to CSV files pertaining to the protocol used.

To exit, bring iperf3 to foreground and ctrl-c, then exit the Mahimahi process and terminate the server on the other window.
