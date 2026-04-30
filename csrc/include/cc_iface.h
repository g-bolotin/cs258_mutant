#ifndef CC_IFACE_H
#define CC_IFACE_H

#include <stdio.h>

// Struct to hold state and metrics
typedef struct {
    int flow_id;
    double smoothed_rtt;
    double min_rtt;
    double delivery_rate;
    double cwnd;
    int loss_events;
    double queueing_estimate;
    char current_protocol[32];
    long last_switch_timestamp;
} FlowState;

void set_protocol(int flow_id, const char* protocol_name);
FlowState get_state(int flow_id);
void get_metrics(int flow_id); // Prints metrics for CLI consumption

#endif // CC_IFACE_H