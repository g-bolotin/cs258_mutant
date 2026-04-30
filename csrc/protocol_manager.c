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

// We use a localized struct here to grab all the extra features Python needs
typedef struct {
    char current_protocol[32];
    double smoothed_rtt;
    double mdev_us;
    double min_rtt;
    double cwnd;
    double advmss;
    double delivered;
    double lost_out;
    double in_flight; // mapped from unacked
    double retrans_out;
    double delivery_rate;
    double throughput_mbps;
    double loss;
} FullState;

FullState get_extended_state(int flow_id) {
    FullState best_state;
    memset(&best_state, 0, sizeof(best_state));
    strncpy(best_state.current_protocol, "unknown", sizeof(best_state.current_protocol));

    FILE *fp = popen("ss -ti state established dst 10.0.0.1:5201", "r");
    if (fp == NULL) {
        printf("Failed to run ss command\n");
        return best_state;
    }

    char line[512];
    double max_cwnd = -1.0; // Track highest cwnd to ignore idle control sockets

    while (fgets(line, sizeof(line), fp) != NULL) {
        FullState temp_state;
        memset(&temp_state, 0, sizeof(temp_state));

        // 1. Identify the protocol
        const char* known_protocols[] = {"cubic", "hybla", "bbr", "westwood", "veno", "vegas", "yeah", "bic", "htcp", "highspeed", "illinois"};
        int num_protocols = 11;
        for (int i = 0; i < num_protocols; i++) {
            if (strstr(line, known_protocols[i])) {
                strncpy(temp_state.current_protocol, known_protocols[i], sizeof(temp_state.current_protocol));
                break;
            }
        }

        // 2. Parse TCP Info Key-Value pairs
        char *token = strtok(line, " \t\n");
        while (token != NULL) {
            char *colon = strchr(token, ':');

            if (colon) {
                *colon = '\0';
                char *key = token;
                char *value = colon + 1;

                if (strcmp(key, "cwnd") == 0) sscanf(value, "%lf", &temp_state.cwnd);
                else if (strcmp(key, "rtt") == 0) {
                    // rtt comes formatted as RTT/MDEV (e.g., 32.4/0.8)
                    sscanf(value, "%lf/%lf", &temp_state.smoothed_rtt, &temp_state.mdev_us);
                }
                else if (strcmp(key, "minrtt") == 0) sscanf(value, "%lf", &temp_state.min_rtt);
                else if (strcmp(key, "advmss") == 0) sscanf(value, "%lf", &temp_state.advmss);
                else if (strcmp(key, "delivered") == 0) sscanf(value, "%lf", &temp_state.delivered);
                else if (strcmp(key, "unacked") == 0) sscanf(value, "%lf", &temp_state.in_flight);
                else if (strcmp(key, "retrans") == 0) {
                    // Format is usually retrans:0/1
                    char* slash = strchr(value, '/');
                    if (slash) sscanf(slash + 1, "%lf", &temp_state.retrans_out);
                }
                else if (strcmp(key, "lost") == 0) sscanf(value, "%lf", &temp_state.lost_out);
            }
            else if (strcmp(token, "send") == 0) {
                token = strtok(NULL, " \t\n");
                if (token) sscanf(token, "%lf", &temp_state.throughput_mbps);
            }
            else if (strcmp(token, "delivery_rate") == 0) {
                token = strtok(NULL, " \t\n");
                if (token) sscanf(token, "%lf", &temp_state.delivery_rate);
            }

            token = strtok(NULL, " \t\n");
        }

        // 3. Find the FAT flow (Data Socket) by checking CWND size
        if (temp_state.cwnd > max_cwnd) {
            max_cwnd = temp_state.cwnd;
            best_state = temp_state;
        }
    }
    pclose(fp);
    return best_state;
}

// Keep the cc_iface.h stub happy but route the logic to the new struct
FlowState get_state(int flow_id) {
    FlowState fs;
    return fs;
}

void get_metrics(int flow_id) {
    FullState s = get_extended_state(flow_id);

    // Output ALL features expected by Python in a strict JSON format
    printf("{\"protocol\": \"%s\", \"rtt_ms\": %.2f, \"smoothed_rtt\": %.2f, \"mdev_us\": %.2f, "
           "\"min_rtt\": %.2f, \"cwnd\": %.0f, \"advmss\": %.0f, \"delivered\": %.0f, "
           "\"lost_out\": %.0f, \"in_flight\": %.0f, \"retrans_out\": %.0f, "
           "\"delivery_rate\": %.2f, \"throughput_mbps\": %.2f, \"loss\": %.0f}\n",
           s.current_protocol, s.smoothed_rtt, s.smoothed_rtt, s.mdev_us,
           s.min_rtt, s.cwnd, s.advmss, s.delivered,
           s.lost_out, s.in_flight, s.retrans_out,
           s.delivery_rate, s.throughput_mbps, s.lost_out);
}

void reset(int flow_id) {
    printf("[KERNEL/NETLINK STUB] Reset flow %d to default state.\n", flow_id);
}

void shutdown_flow(int flow_id) {
    printf("[KERNEL/NETLINK STUB] Shut down tracking for flow %d.\n", flow_id);
}