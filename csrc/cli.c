#include "include/cc_iface.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

void print_usage() {
    printf("Usage:\n");
    printf("  ./protocol_manager --flow <id> --set <protocol>\n");
    printf("  ./protocol_manager --flow <id> --read-state\n");
    printf("  ./protocol_manager --flow <id> --read-metrics\n");
}

int main(int argc, char *argv[]) {
    if (argc < 4) {
        print_usage();
        return 1;
    }

    int flow_id = -1;

    // Basic argument parsing to match recommended CLI usage
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--flow") == 0 && i + 1 < argc) {
            flow_id = atoi(argv[++i]);
        }
        else if (strcmp(argv[i], "--set") == 0 && i + 1 < argc && flow_id != -1) {
            return set_protocol(flow_id, argv[++i]) == 0 ? 0 : 1;
        }
        else if (strcmp(argv[i], "--read-state") == 0 && flow_id != -1) {
            FlowState state = get_state(flow_id);
            printf("Flow %d State: Protocol=%s, RTT=%.2fms, LossEvents=%d\n",
                   state.flow_id, state.current_protocol, state.smoothed_rtt, state.loss_events);
            return 0;
        }
        else if (strcmp(argv[i], "--read-metrics") == 0 && flow_id != -1) {
            return get_metrics(flow_id) == 0 ? 0 : 1;
        }
    }

    print_usage();
    return 1;
}
