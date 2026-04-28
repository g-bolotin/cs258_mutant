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
        FlowState temp_state = best_state;

        // 1. Identify the protocol first
        const char* known_protocols[] = {"cubic", "hybla", "bbr", "westwood", "veno", "vegas", "yeah", "bic", "htcp", "highspeed", "illinois"};
        int num_protocols = 11;
        for (int i = 0; i < num_protocols; i++) {
            if (strstr(line, known_protocols[i])) {
                strncpy(temp_state.current_protocol, known_protocols[i], sizeof(temp_state.current_protocol));
                break;
            }
        }

        // 2. Automatically parse all key:value pairs dynamically
        char *token = strtok(line, " \t\n");
        while (token != NULL) {
            char *colon = strchr(token, ':');

            if (colon) {
                *colon = '\0';
                char *key = token;
                char *value = colon + 1;

                if (strcmp(key, "rtt") == 0) {
                    sscanf(value, "%lf", &temp_state.smoothed_rtt);
                }
                else if (strcmp(key, "cwnd") == 0) {
                    sscanf(value, "%lf", &temp_state.cwnd);
                }
                // Add new metrics here if needed
            }
            // Handle edge cases where 'ss' uses a space instead of a colon (like delivery_rate)
            else if (strcmp(token, "delivery_rate") == 0 || strcmp(token, "send") == 0) {
                token = strtok(NULL, " \t\n");
                if (token) sscanf(token, "%lf", &temp_state.delivery_rate);
            }

            token = strtok(NULL, " \t\n");
        }

        // 3. Evaluate if this connection is the Data Channel
        if (temp_state.delivery_rate > max_rate) {
            max_rate = temp_state.delivery_rate;
            best_state = temp_state;
        }
    }
    pclose(fp);
    return best_state;
}

void get_metrics(int flow_id) {
    FlowState state = get_state(flow_id);
    // Print in JSON format including the new cwnd metric
    // Change "delivery_rate" to "throughput_mbps" in the JSON string
    printf("{\"protocol\": \"%s\", \"rtt_ms\": %.2f, \"cwnd\": %.0f, \"throughput_mbps\": %.2f}\n",
           state.current_protocol, state.smoothed_rtt, state.cwnd, state.delivery_rate);
}

void reset(int flow_id) {
    printf("[KERNEL/NETLINK STUB] Reset flow %d to default state.\n", flow_id);
}

void shutdown_flow(int flow_id) {
    printf("[KERNEL/NETLINK STUB] Shut down tracking for flow %d.\n", flow_id);
}