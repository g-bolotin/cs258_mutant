#include "include/cc_iface.h"

#include <errno.h>
#include <linux/netlink.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>

#define MUTANT_NETLINK_USER 25
#define MUTANT_RECV_BUF_SIZE 1024
#define MUTANT_RECV_TIMEOUT_MS 250
#define MUTANT_MAX_RECV_ATTEMPTS 8

enum {
    MUTANT_COMM_END = 0,
    MUTANT_COMM_BEGIN = 1,
    MUTANT_COMM_SELECT_ARM = 2,
    MUTANT_COMM_TEST = 3
};

enum {
    MUTANT_ARM_CUBIC = 0,
    MUTANT_ARM_HYBLA = 1,
    MUTANT_ARM_BBR = 2,
    MUTANT_ARM_WESTWOOD = 3,
    MUTANT_ARM_VENO = 4,
    MUTANT_ARM_VEGAS = 5,
    MUTANT_ARM_YEAH = 6,
    MUTANT_ARM_BIC = 7,
    MUTANT_ARM_HTCP = 8,
    MUTANT_ARM_ILLINOIS = 9,
    MUTANT_ARM_CDG = 10
};

typedef struct {
    const char *name;
    uint32_t arm_id;
    int is_alias;
} ProtocolMap;

static const ProtocolMap k_protocols[] = {
    {"cubic", MUTANT_ARM_CUBIC, 0},
    {"hybla", MUTANT_ARM_HYBLA, 0},
    {"bbr", MUTANT_ARM_BBR, 0},
    {"westwood", MUTANT_ARM_WESTWOOD, 0},
    {"veno", MUTANT_ARM_VENO, 0},
    {"vegas", MUTANT_ARM_VEGAS, 0},
    {"yeah", MUTANT_ARM_YEAH, 0},
    {"bic", MUTANT_ARM_BIC, 0},
    {"htcp", MUTANT_ARM_HTCP, 0},
    {"illinois", MUTANT_ARM_ILLINOIS, 0},
    {"cdg", MUTANT_ARM_CDG, 0},
    {"highspeed", MUTANT_ARM_ILLINOIS, 1}
};

typedef struct {
    uint32_t now;
    uint32_t snd_cwnd;
    uint32_t rtt_us;
    uint32_t srtt_us;
    uint32_t mdev_us;
    uint32_t min_rtt;
    uint32_t advmss;
    uint32_t delivered;
    uint32_t lost_out;
    uint32_t packets_out;
    uint32_t retrans_out;
    uint64_t rate;
    uint32_t prev_proto_id;
    uint32_t selected_proto_id;
    uint64_t throughput_bps;
    uint32_t loss_rate;
} MutantInfo;

typedef struct {
    int fd;
    uint32_t port_id;
} NetlinkClient;

static const ProtocolMap *find_protocol_by_name(const char *name)
{
    size_t i;

    if (name == NULL) {
        return NULL;
    }

    for (i = 0; i < sizeof(k_protocols) / sizeof(k_protocols[0]); i++) {
        if (strcmp(name, k_protocols[i].name) == 0) {
            return &k_protocols[i];
        }
    }

    return NULL;
}

static const char *find_protocol_name_by_id(uint32_t arm_id)
{
    size_t i;

    for (i = 0; i < sizeof(k_protocols) / sizeof(k_protocols[0]); i++) {
        if (k_protocols[i].arm_id == arm_id && !k_protocols[i].is_alias) {
            return k_protocols[i].name;
        }
    }

    return "unknown";
}

static int netlink_open(NetlinkClient *client)
{
    struct sockaddr_nl local_addr;
    struct sockaddr_nl kernel_addr;

    memset(client, 0, sizeof(*client));
    client->fd = -1;

    client->fd = socket(AF_NETLINK, SOCK_RAW, MUTANT_NETLINK_USER);
    if (client->fd < 0) {
        return -1;
    }

    memset(&local_addr, 0, sizeof(local_addr));
    local_addr.nl_family = AF_NETLINK;
    local_addr.nl_pid = (uint32_t)getpid();
    local_addr.nl_groups = 0;

    if (bind(client->fd, (struct sockaddr *)&local_addr, sizeof(local_addr)) < 0) {
        close(client->fd);
        client->fd = -1;
        return -1;
    }

    memset(&kernel_addr, 0, sizeof(kernel_addr));
    kernel_addr.nl_family = AF_NETLINK;
    kernel_addr.nl_pid = 0;
    kernel_addr.nl_groups = 0;

    if (connect(client->fd, (struct sockaddr *)&kernel_addr, sizeof(kernel_addr)) < 0) {
        close(client->fd);
        client->fd = -1;
        return -1;
    }

    client->port_id = local_addr.nl_pid;
    return 0;
}

static void netlink_close(NetlinkClient *client)
{
    if (client == NULL) {
        return;
    }
    if (client->fd >= 0) {
        close(client->fd);
        client->fd = -1;
    }
}

static int netlink_send(NetlinkClient *client, uint16_t comm_flag, uint32_t seq)
{
    char payload[] = "1";
    size_t payload_len = sizeof(payload);
    size_t msg_len = NLMSG_SPACE(payload_len);
    struct nlmsghdr *nlh = NULL;
    int ret = -1;

    if (client == NULL || client->fd < 0) {
        return -1;
    }

    nlh = calloc(1, msg_len);
    if (nlh == NULL) {
        return -1;
    }

    nlh->nlmsg_len = NLMSG_LENGTH(payload_len);
    nlh->nlmsg_pid = client->port_id;
    nlh->nlmsg_flags = comm_flag;
    nlh->nlmsg_seq = seq;
    memcpy(NLMSG_DATA(nlh), payload, payload_len);

    if (send(client->fd, nlh, nlh->nlmsg_len, 0) >= 0) {
        ret = 0;
    }

    free(nlh);
    return ret;
}

static int netlink_recv_payload(NetlinkClient *client, char *buffer, size_t buffer_len, int timeout_ms)
{
    struct pollfd pfd;
    char recv_buf[MUTANT_RECV_BUF_SIZE];
    ssize_t bytes_read;
    struct nlmsghdr *nlh;
    size_t payload_len;
    int poll_ret;

    if (client == NULL || client->fd < 0 || buffer == NULL || buffer_len == 0) {
        return -1;
    }

    pfd.fd = client->fd;
    pfd.events = POLLIN;
    pfd.revents = 0;

    poll_ret = poll(&pfd, 1, timeout_ms);
    if (poll_ret <= 0 || (pfd.revents & POLLIN) == 0) {
        return -1;
    }

    bytes_read = recv(client->fd, recv_buf, sizeof(recv_buf), 0);
    if (bytes_read < 0) {
        return -1;
    }
    if ((size_t)bytes_read < sizeof(struct nlmsghdr)) {
        return -1;
    }

    nlh = (struct nlmsghdr *)recv_buf;
    if (!NLMSG_OK(nlh, (unsigned int)bytes_read)) {
        return -1;
    }

    payload_len = NLMSG_PAYLOAD(nlh, 0);
    if (payload_len >= buffer_len) {
        payload_len = buffer_len - 1;
    }
    memcpy(buffer, NLMSG_DATA(nlh), payload_len);
    buffer[payload_len] = '\0';

    return (int)payload_len;
}

static int parse_mutant_info(const char *payload, MutantInfo *info)
{
    char scratch[512];
    char *token;
    char *saveptr = NULL;
    unsigned long long fields[16];
    char *endptr;
    size_t i = 0;
    size_t payload_len;

    if (payload == NULL || info == NULL) {
        return -1;
    }

    payload_len = strnlen(payload, sizeof(scratch) - 1);
    memcpy(scratch, payload, payload_len);
    scratch[payload_len] = '\0';

    token = strtok_r(scratch, ";", &saveptr);
    while (token != NULL && i < (sizeof(fields) / sizeof(fields[0]))) {
        errno = 0;
        endptr = NULL;
        fields[i] = strtoull(token, &endptr, 10);
        if (errno != 0 || endptr == token || *endptr != '\0') {
            return -1;
        }
        i++;
        token = strtok_r(NULL, ";", &saveptr);
    }

    if (i < (sizeof(fields) / sizeof(fields[0]))) {
        return -1;
    }

    info->now = (uint32_t)fields[0];
    info->snd_cwnd = (uint32_t)fields[1];
    info->rtt_us = (uint32_t)fields[2];
    info->srtt_us = (uint32_t)fields[3];
    info->mdev_us = (uint32_t)fields[4];
    info->min_rtt = (uint32_t)fields[5];
    info->advmss = (uint32_t)fields[6];
    info->delivered = (uint32_t)fields[7];
    info->lost_out = (uint32_t)fields[8];
    info->packets_out = (uint32_t)fields[9];
    info->retrans_out = (uint32_t)fields[10];
    info->rate = fields[11];
    info->prev_proto_id = (uint32_t)fields[12];
    info->selected_proto_id = (uint32_t)fields[13];
    info->throughput_bps = fields[14];
    info->loss_rate = (uint32_t)fields[15];
    return 0;
}

static int begin_session(NetlinkClient *client)
{
    if (netlink_send(client, MUTANT_COMM_END, 0) != 0) {
        /* Best effort cleanup only. */
    }
    return netlink_send(client, MUTANT_COMM_BEGIN, 0);
}

static int fetch_info(MutantInfo *info)
{
    NetlinkClient client;
    char payload[MUTANT_RECV_BUF_SIZE];
    int attempts;

    if (netlink_open(&client) != 0) {
        return -1;
    }

    if (begin_session(&client) != 0) {
        netlink_close(&client);
        return -1;
    }

    for (attempts = 0; attempts < MUTANT_MAX_RECV_ATTEMPTS; attempts++) {
        int payload_len = netlink_recv_payload(&client, payload, sizeof(payload), MUTANT_RECV_TIMEOUT_MS);
        if (payload_len <= 0) {
            continue;
        }

        if (strcmp(payload, "0") == 0 || strcmp(payload, "-1") == 0) {
            continue;
        }

        if (parse_mutant_info(payload, info) == 0) {
            netlink_close(&client);
            return 0;
        }
    }

    netlink_close(&client);
    return -1;
}

int set_protocol(int flow_id, const char *protocol_name)
{
    const ProtocolMap *entry;
    NetlinkClient client;

    (void)flow_id;
    entry = find_protocol_by_name(protocol_name);
    if (entry == NULL) {
        fprintf(stderr, "Unsupported protocol '%s'\n", protocol_name ? protocol_name : "(null)");
        return -1;
    }

    if (netlink_open(&client) != 0) {
        fprintf(stderr, "Failed to open netlink socket: %s\n", strerror(errno));
        return -1;
    }

    if (begin_session(&client) != 0) {
        fprintf(stderr, "Failed to begin netlink session: %s\n", strerror(errno));
        netlink_close(&client);
        return -1;
    }

    if (netlink_send(&client, MUTANT_COMM_SELECT_ARM, entry->arm_id) != 0) {
        fprintf(stderr, "Failed to select protocol via netlink: %s\n", strerror(errno));
        netlink_close(&client);
        return -1;
    }

    if (entry->is_alias) {
        printf("Mapped legacy protocol '%s' to '%s' (arm_id=%u)\n",
               protocol_name, find_protocol_name_by_id(entry->arm_id), entry->arm_id);
    } else {
        printf("Selected protocol: %s (arm_id=%u)\n", protocol_name, entry->arm_id);
    }

    netlink_close(&client);
    return 0;
}

FlowState get_state(int flow_id)
{
    FlowState state;
    MutantInfo info;
    const char *protocol_name;
    double srtt_ms;
    double min_rtt_ms;

    memset(&state, 0, sizeof(state));
    state.flow_id = flow_id;
    strncpy(state.current_protocol, "unknown", sizeof(state.current_protocol) - 1);
    state.current_protocol[sizeof(state.current_protocol) - 1] = '\0';

    if (fetch_info(&info) != 0) {
        return state;
    }

    protocol_name = find_protocol_name_by_id(info.selected_proto_id);
    strncpy(state.current_protocol, protocol_name, sizeof(state.current_protocol) - 1);
    state.current_protocol[sizeof(state.current_protocol) - 1] = '\0';

    srtt_ms = (double)info.srtt_us / 8000.0;
    min_rtt_ms = (double)info.min_rtt / 1000.0;

    state.smoothed_rtt = srtt_ms;
    state.min_rtt = min_rtt_ms;
    state.delivery_rate = (double)info.rate;
    state.cwnd = (double)info.snd_cwnd;
    state.loss_events = (int)info.lost_out;
    state.queueing_estimate = srtt_ms > min_rtt_ms ? (srtt_ms - min_rtt_ms) : 0.0;
    state.last_switch_timestamp = (long)info.now;
    return state;
}

int get_metrics(int flow_id)
{
    MutantInfo info;
    const char *protocol_name;
    double rtt_ms;
    double smoothed_rtt_ms;
    double min_rtt_ms;
    double throughput_mbps;

    (void)flow_id;

    if (fetch_info(&info) != 0) {
        fprintf(stderr, "Failed to fetch metrics from mutant kernel module via netlink\n");
        return -1;
    }

    protocol_name = find_protocol_name_by_id(info.selected_proto_id);
    rtt_ms = (double)info.rtt_us / 1000.0;
    smoothed_rtt_ms = (double)info.srtt_us / 8000.0;
    min_rtt_ms = (double)info.min_rtt / 1000.0;
    throughput_mbps = (double)info.throughput_bps / 1000000.0;

    printf("{\"protocol\": \"%s\", \"rtt_ms\": %.3f, \"smoothed_rtt\": %.3f, \"mdev_us\": %.0f, "
           "\"min_rtt\": %.3f, \"cwnd\": %.0f, \"advmss\": %.0f, \"delivered\": %.0f, "
           "\"lost_out\": %.0f, \"in_flight\": %.0f, \"retrans_out\": %.0f, "
           "\"delivery_rate\": %.0f, \"throughput_mbps\": %.3f, \"loss\": %.0f, "
           "\"loss_rate\": %.0f, \"prev_proto\": %u, \"crt_proto\": %u}\n",
           protocol_name, rtt_ms, smoothed_rtt_ms, (double)info.mdev_us,
           min_rtt_ms, (double)info.snd_cwnd, (double)info.advmss, (double)info.delivered,
           (double)info.lost_out, (double)info.packets_out, (double)info.retrans_out,
           (double)info.rate, throughput_mbps, (double)info.lost_out,
           (double)info.loss_rate, info.prev_proto_id, info.selected_proto_id);

    return 0;
}
