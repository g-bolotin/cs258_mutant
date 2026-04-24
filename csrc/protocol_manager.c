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
    FlowState best_state;
    best_state.flow_id = flow_id;
    best_state.smoothed_rtt = 0.0;
    best_state.delivery_rate = 0.0;
    best_state.loss_events = 0;
    strncpy(best_state.current_protocol, "unknown", sizeof(best_state.current_protocol));

    // Force ss to look specifically at the Mahimahi server IP
    // FILE *fp = popen("ss -ti dst 10.0.0.1:5201", "r");
    FILE *fp = popen("ss -ti state established dst 10.0.0.1:5201", "r");
    if (fp == NULL) {
        printf("Failed to run ss command\n");
        return best_state;
    }

    char line[256];
    double max_rate = -1.0;

    // Read every line from the ss output
    while (fgets(line, sizeof(line), fp) != NULL) {
        if (strstr(line, "cubic") || strstr(line, "bbr") || strstr(line, "vegas")) {

            FlowState temp_state = best_state; // Start with defaults

            // Extract protocol
            if (strstr(line, "bbr")) strncpy(temp_state.current_protocol, "bbr", sizeof(temp_state.current_protocol));
            else if (strstr(line, "vegas")) strncpy(temp_state.current_protocol, "vegas", sizeof(temp_state.current_protocol));
            else strncpy(temp_state.current_protocol, "cubic", sizeof(temp_state.current_protocol));

            // Extract RTT
            char *rtt_ptr = strstr(line, "rtt:");
            if (rtt_ptr) {
                sscanf(rtt_ptr, "rtt:%lf", &temp_state.smoothed_rtt);
            }

            // Extract Congestion Window (cwnd)
            char *cwnd_ptr = strstr(line, "cwnd:");
            if (cwnd_ptr) {
                sscanf(cwnd_ptr, "cwnd:%lf", &temp_state.cwnd);
            }

            // Extract delivery rate (using a space instead of a colon)
            char *rate_ptr = strstr(line, "delivery_rate ");
            if (rate_ptr) {
                sscanf(rate_ptr, "delivery_rate %lf", &temp_state.delivery_rate);
            } else {
                // Fallback: Use 'send' rate if delivery_rate is missing on loopback
                rate_ptr = strstr(line, "send ");
                if (rate_ptr) {
                    sscanf(rate_ptr, "send %lf", &temp_state.delivery_rate);
                }
            }

            // If this connection has a higher throughput than our previous best, it's the data channel!
            if (temp_state.delivery_rate > max_rate) {
                max_rate = temp_state.delivery_rate;
                best_state = temp_state;
            }
        }
    }
    pclose(fp);
    return best_state;
}

void get_metrics(int flow_id) {
    FlowState state = get_state(flow_id);
    // Print in JSON format including the new cwnd metric
    printf("{\"flow_id\": %d, \"protocol\": \"%s\", \"rtt_ms\": %.2f, \"throughput_mbps\": %.2f, \"cwnd\": %.0f, \"loss\": %d}\n",
           state.flow_id, state.current_protocol, state.smoothed_rtt, state.delivery_rate, state.cwnd, state.loss_events);
}

void reset(int flow_id) {
    printf("[KERNEL/NETLINK STUB] Reset flow %d to default state.\n", flow_id);
}

void shutdown_flow(int flow_id) {
    printf("[KERNEL/NETLINK STUB] Shut down tracking for flow %d.\n", flow_id);
}