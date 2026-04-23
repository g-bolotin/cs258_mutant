#include <stdio.h>
#include <stdlib.h>

#include "include/cc_iface.h"
#include <string.h>
#include <time.h>

void init(int flow_id, const char* protocol_pool) {
    printf("[KERNEL/NETLINK STUB] Initialized flow %d with pool: %s\n", flow_id, protocol_pool);
}

void set_protocol(int flow_id, const char* protocol_name) {
    char command[256];
    // Write the new protocol directly to the procfs system file
    snprintf(command, sizeof(command), "sysctl -w net.ipv4.tcp_congestion_control=%s > /dev/null 2>&1", protocol_name);

    int ret = system(command);
    if (ret == 0) {
        printf("Successfully switched to protocol: %s\n", protocol_name);
    } else {
        printf("Failed to switch to %s. Did you run with sudo?\n", protocol_name);
    }
}

FlowState get_state(int flow_id) {
    FlowState state;
    // Default fallback values
    state.flow_id = flow_id;
    state.smoothed_rtt = 0.0;
    state.delivery_rate = 0.0;
    state.loss_events = 0;
    strncpy(state.current_protocol, "unknown", sizeof(state.current_protocol));

    // Run the 'ss' command to get TCP info for all active connections
    // Only look at connections talking to an iperf3 server
    FILE *fp = popen("ss -ti dst :5201", "r");
    if (fp == NULL) {
        printf("Failed to run ss command\n");
        return state;
    }

    char line[256];
    // Read the output line by line
    while (fgets(line, sizeof(line), fp) != NULL) {
        // ss -ti outputs the connection on one line, and the TCP stats on the next line.
        // We look for the stats line containing the algorithm and rtt.
        if (strstr(line, "cubic") || strstr(line, "bbr") || strstr(line, "vegas")) {

            // Extract the protocol name
            if (strstr(line, "bbr")) strncpy(state.current_protocol, "bbr", sizeof(state.current_protocol));
            else if (strstr(line, "vegas")) strncpy(state.current_protocol, "vegas", sizeof(state.current_protocol));
            else strncpy(state.current_protocol, "cubic", sizeof(state.current_protocol));

            // Extract the RTT (format usually looks like rtt:45.2/1.5)
            char *rtt_ptr = strstr(line, "rtt:");
            if (rtt_ptr) {
                sscanf(rtt_ptr, "rtt:%lf", &state.smoothed_rtt);
            }

            // Extract delivery rate (format usually looks like delivery_rate:120.5Mbps)
            char *rate_ptr = strstr(line, "delivery_rate:");
            if (rate_ptr) {
                sscanf(rate_ptr, "delivery_rate:%lf", &state.delivery_rate);
            }

            // Break after finding the first active data flow
            // (You will need to refine this later to match the specific flow_id/port)
            break;
        }
    }
    pclose(fp);
    return state;
}

void get_metrics(int flow_id) {
    FlowState state = get_state(flow_id);
    // Print in a format easily parsed by Python later (e.g., JSON or CSV) [cite: 15]
    printf("{\"flow_id\": %d, \"protocol\": \"%s\", \"rtt_ms\": %.2f, \"throughput_mbps\": %.2f, \"loss\": %d}\n",
           state.flow_id, state.current_protocol, state.smoothed_rtt, state.delivery_rate, state.loss_events);
}

void reset(int flow_id) {
    printf("[KERNEL/NETLINK STUB] Reset flow %d to default state.\n", flow_id);
}

void shutdown_flow(int flow_id) {
    printf("[KERNEL/NETLINK STUB] Shut down tracking for flow %d.\n", flow_id);
}