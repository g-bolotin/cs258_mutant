#include <stdio.h>

#include "include/cc_iface.h"
#include <string.h>
#include <time.h>

void init(int flow_id, const char* protocol_pool) {
    printf("[KERNEL/NETLINK STUB] Initialized flow %d with pool: %s\n", flow_id, protocol_pool);
}

void set_protocol(int flow_id, const char* protocol_name) {
    // TODO: Implement actual Netlink message to switch protocol here
    printf("[KERNEL/NETLINK STUB] Successfully switched flow %d to protocol: %s\n", flow_id, protocol_name);
}

FlowState get_state(int flow_id) {
    // TODO: Read actual low-overhead metrics from kernel
    FlowState state;
    state.flow_id = flow_id;
    state.smoothed_rtt = 45.2; // Dummy data
    state.min_rtt = 40.0;
    state.delivery_rate = 120.5;
    state.loss_events = 2;
    state.queueing_estimate = 5.2;
    strncpy(state.current_protocol, "cubic", sizeof(state.current_protocol));
    state.last_switch_timestamp = time(NULL);
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