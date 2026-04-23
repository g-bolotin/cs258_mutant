#ifndef CC_IFACE_H
#define CC_IFACE_H

#include <stdio.h>

// Struct to hold state and metrics
typedef struct {
    int flow_id;
    double smoothed_rtt;
    double min_rtt;
    double delivery_rate;
    int loss_events;
    double queueing_estimate;
    char current_protocol[32];
    long last_switch_timestamp;
} FlowState;

// The tiny C interface boundary
void init(int flow_id, const char* protocol_pool);
void set_protocol(int flow_id, const char* protocol_name);
FlowState get_state(int flow_id);
void get_metrics(int flow_id); // Prints metrics for CLI consumption
void reset(int flow_id);
void shutdown_flow(int flow_id);

#endif // CC_IFACE_H