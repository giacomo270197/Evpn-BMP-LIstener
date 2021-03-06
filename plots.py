import sys
import requests
import json
import dateutil.parser
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker
from matplotlib.colors import ListedColormap
import matplotlib
import math
import numpy
import statistics
import networkx as nx
import hashlib

es_host = None
es_port = None
es_index = None
target = None

tolerance = 1

nlri_possibilities = ["MP_NLRI_REACH", "MP_NLRI_UNREACH"]

rd_to_anycast = {
    "10.10.10.1:0 6": "10.10.100.1",
    "10.10.10.2:0 6": "10.10.100.1",
    "10.10.10.3:0 6": "10.10.100.2",
    "10.10.10.4:0 6": "10.10.100.2",
}


class EventTree:
    def __init__(self):
        self.tree = nx.DiGraph()
        self.source_nodes = []
        self.nodes_to_add = []

    def add_to_source(self, node):
        self.source_nodes.append(node)

    def rm_from_source(self, node):
        rm = []
        for x in self.source_nodes:
            if node in x:
                rm.append(x)
        for x in rm:
            try:
                self.source_nodes.pop(self.source_nodes.index(x))
            except:
                pass
        return rm

    def add_to_to_add(self, node):
        self.nodes_to_add.append(node)

    def rm_from_to_add(self, node):
        rm = []
        for x in self.nodes_to_add:
            if node in x:
                rm.append(x)
        for x in rm:
            try:
                self.nodes_to_add.pop(self.nodes_to_add.index(x))
            except:
                pass
        return rm

    def in_source_nodes(self, node):
        rm = []
        for x in self.source_nodes:
            if node in x:
                rm.append(x)
        if rm:
            return True
        return False

    def add_new_layer(self):
        if not self.source_nodes:
            self.tree.add_node(self.nodes_to_add[0])
        for s_node in self.source_nodes:
            for d_node in self.nodes_to_add:
                self.tree.add_node(d_node)
                self.tree.add_edge(s_node, d_node)


def find_best_placement(total):
    sqrt = math.sqrt(total)
    n_cols = math.ceil(sqrt)
    n_row = math.floor(sqrt)
    if n_cols * n_row < total:
        n_row += 1
    return n_row, n_cols


def divide(event, event_times):
    event_div = [[], []]
    event_times_div = [[], []]
    for i in range(len(event)):
        if event[i] == "MP_NLRI_REACH":
            event_div[0].append(event[i])
            event_times_div[0].append(event_times[i])
        else:
            event_div[1].append(event[i])
            event_times_div[1].append(event_times[i])
    return event_div, event_times_div


def plot(events, events_times, new_advertisers, withdrawn_advertisers):
    matplotlib.rcParams['axes.prop_cycle'] = matplotlib.cycler(color=[
                                                               "b", "r"])
    for event, i in zip(events, range(len(events))):
        plt.gca().xaxis.set_major_formatter(
            mdates.DateFormatter("%M:%S"))  # ("%Y-%m-%d %H:%M:%S"))
        locator = mdates.SecondLocator()
        plt.gca().xaxis.set_major_locator(locator)
        event_div, event_times_div = divide(event, events_times[i])
        plt.gca().yaxis.set_visible(False)
        tmp_n = set(new_advertisers[i])
        tmp_w = set(withdrawn_advertisers[i])
        try:
            tmp_n.remove(None)
            tmp_w.remove(None)
        except KeyError:
            pass
        plt.scatter(event_times_div[0], event_div[0],
                    label="MP_NLRI_REACH\n{}".format(tmp_n))
        plt.scatter(event_times_div[1], event_div[1],
                    label="MP_NLRI_UNREACH\n{}".format(tmp_w))
        plt.legend(loc='best')
        plt.xlabel('Time')
        plt.gcf().autofmt_xdate()
        plt.show()


def compute_convergence(event_times):
    tmp = []
    for times in event_times:
        tmp.append((times[-1] - times[0]).total_seconds())
    print("Convergence Mean: {}".format(statistics.mean(tmp)))
    print("Convergence Stdev: {}".format(statistics.stdev(tmp)))


def set_es_parameters():
    global es_host
    global es_port
    global es_index
    with open("config.txt", "r") as file:
        es_host = file.readline().replace("\n", "")
        es_port = file.readline().replace("\n", "")
        es_index = file.readline().replace("\n", "")


def launch_request(query):
    header = {
        "Content-Type": "application/json"
    }
    response = requests.get(
        "http://{}:{}/{}/_search/?size=10000".format(es_host, es_port, target), data=json.dumps(query), headers=header)
    return response.json()


def retrieve_mac_info(mac):
    query = {
        "query": {
            "term": {
                "bgp_message.update.mac_address.keyword": {
                    "value": mac
                }
            }
        }
    }
    return launch_request(query)


def retrieve_updates():
    query = {
        "query": {
            "term": {
                "bgp_message.message_type.keyword": {
                    "value": "UPDATE"
                }
            }
        }
    }
    return launch_request(query)


def retrieve_opens():
    query = {
        "query": {
            "term": {
                "bgp_message.message_type.keyword": {
                    "value": "OPEN"
                }
            }
        }
    }
    return launch_request(query)


def retrieve_ceases():
    query = {
        "query": {
            "term": {
                "bgp_message.notification.error_code": {
                    "value": "6"
                }
            }
        }
    }
    return launch_request(query)


def find_mean_timedelta(adv_timestamps, adv):
    mean_delta = 0
    count = 0
    intervals = []
    for x in range(len(adv_timestamps) - 1):
        intervals.append((adv_timestamps[x+1] -
                          adv_timestamps[x]).total_seconds())
        # print(intervals[-1])
        count += 1
    mean_delta = statistics.mean(intervals)
    stdev_delta = statistics.stdev(intervals)
    return mean_delta, stdev_delta


def find_events(adv, adv_timestamps):
    events = []
    events_times = []
    delimiters = []
    bgn = 0
    mean_delta, stdev_delta = find_mean_timedelta(adv_timestamps, adv)
    print((mean_delta) * (len(adv) / (stdev_delta)))
    for x in range(len(adv_timestamps) - 1):
        if (adv_timestamps[x+1] - adv_timestamps[x]).total_seconds() > (mean_delta) * (tolerance * len(adv) / (stdev_delta)):
            delimiters.append(x)
    for x in delimiters:
        events.append(adv[bgn:x+1])
        events_times.append(adv_timestamps[bgn:x+1])
        bgn = x + 1
    events.append(adv[bgn:])
    events_times.append(adv_timestamps[bgn:])
    if not events:
        events = adv
        events_times = adv_timestamps
    return events, events_times


def get_advertisers(events, new_advertisers, withdrawn_advertisers):
    tmp_n = []
    tmp_w = []
    last = 0
    for e in events:
        tmp_n.append(new_advertisers[last:(last+len(e))])
        tmp_w.append(withdrawn_advertisers[last:(last+len(e))])
        last += len(e)
    return tmp_n, tmp_w


def analyze_mac(mac):
    mac_info = retrieve_mac_info(mac)["hits"]["hits"]
    tmp = []
    new_advertisers = []
    withdrawn_advertisers = []
    mac_info = sorted(mac_info, key=lambda d: dateutil.parser.isoparse(
        d["_source"]["timestamp_received"]).timestamp())
    for entry in mac_info:
        bmp = entry["_source"]
        adv_type = None
        for up in bmp["bgp_message"]["update"]:
            try:
                if up["type"] == "New Route":
                    try:
                        adv_type = nlri_possibilities[0]
                        new_advertisers.append(
                            rd_to_anycast[up["route_distinguisher"]])
                        withdrawn_advertisers.append(None)
                    except KeyError:
                        pass
                elif up["type"] == "Withdrawn":
                    try:
                        adv_type = nlri_possibilities[1]
                        withdrawn_advertisers.append(
                            rd_to_anycast[up["route_distinguisher"]])
                        new_advertisers.append(None)
                    except KeyError:
                        pass
                tmp.append((adv_type, dateutil.parser.isoparse(
                    bmp["timestamp_received"])))
            except KeyError:
                print("This isn't an update: ",
                      bmp["bgp_message"]["message_type"])
    adv = [x for x, _ in tmp]
    adv_timestamps = [x for _, x in tmp]
    events, events_times = find_events(adv, adv_timestamps)
    new_advertisers, withdrawn_advertisers = get_advertisers(
        events, new_advertisers, withdrawn_advertisers)
    plot(events, events_times, new_advertisers, withdrawn_advertisers)
    compute_convergence(events_times)


def find_all_macs(data):
    macs = []
    lis = [x["_source"]["bgp_message"]["update"] for x in data]
    for x in lis:
        for y in x:
            try:
                macs.append(y["mac_address"])
            except KeyError:
                pass
    macs = set(macs)
    return macs


def find_macs_events(data):
    macs = find_all_macs(data)
    ret = {}
    for mac in macs:
        events = [x for x in data if x["_source"]
                  ["bgp_message"]["update"][0]["mac_address"] == mac]
        events, _ = find_events(events, [dateutil.parser.isoparse(
            x["_source"]["timestamp_received"]) for x in events])
        ret[mac] = events
    return ret


def find_rds(data):
    rds_new = []
    rds_withdrawn = []
    for x in data:
        for u in x["_source"]["bgp_message"]["update"]:
            rd = u["route_distinguisher"]
            if u["type"] == "New Route":
                rds_new.append(rd)
            else:
                rds_withdrawn.append(rd)
    return rds_new, rds_withdrawn


def plot_graph(mac, tree, labels_list):
    plt.plot()
    plt.title = mac
    pos = nx.spring_layout(tree.tree)
    d = dict(tree.tree.degree)
    labels = {}
    for x, y in zip(d.keys(), labels_list):
        labels[x] = y[-1] + " " + x[-8:]
    all_nodes = list(d.keys())
    active_nodes = tree.source_nodes
    pos_red = pos.copy()
    pos_blue = {}
    for n in active_nodes:
        all_nodes.pop(all_nodes.index(n))
        pos_blue[n] = pos_red[n]
        del(pos_red[n])
    print(pos)
    print(pos_red)
    print(pos_blue)
    print(all_nodes)
    print(active_nodes)
    nx.draw_networkx_nodes(tree.tree, pos_red, nodelist=all_nodes,
                           node_size=len(all_nodes) * [500], node_color='r')
    nx.draw_networkx_nodes(tree.tree, pos_blue, nodelist=active_nodes,
                           node_size=len(active_nodes) * [500], node_color='b')
    nx.draw_networkx_edges(tree.tree, pos, width=1.0, alpha=0.5)
    pos_higher = {}
    for k, v in pos.items():
        pos_higher[k] = numpy.array([v[0], v[1]+0.1])
    nx.draw_networkx_labels(tree.tree, pos_higher, labels, font_size=16)
    plt.show()


def detect_flapping():
    updates = retrieve_updates()["hits"]["hits"]
    updates = sorted(updates, key=lambda d: dateutil.parser.isoparse(
        d["_source"]["timestamp_received"]).timestamp())
    mac_events = find_macs_events(updates)
    for mac in mac_events.keys():
        labels = []
        tree = EventTree()
        # print(mac_events[mac])
        for event in mac_events[mac]:
            rds_new, rds_withdrawn = find_rds(event)
            rds_new = list(set([rd_to_anycast[x] for x in rds_new]))
            rds_withdrawn = list(set([rd_to_anycast[x]
                                      for x in rds_withdrawn]))

            if True:  # rds_new and rds_withdrawn:
                print("##########################################")
                print(tree.nodes_to_add)
                print(tree.source_nodes)
                if rds_new and not tree.in_source_nodes(rds_new[0]):
                    for rd in rds_new:
                        print(rd)
                        x = rd + " ,  " + \
                            event[0]["_source"]["timestamp_received"][-15:-7]
                        tree.add_to_to_add(x)
                        labels.append(rd)
                tree.add_new_layer()
                if rds_new and not tree.in_source_nodes(rds_new[0]):
                    for rd in rds_new:
                        print(rd)
                        x = rd + " ,  " + \
                            event[0]["_source"]["timestamp_received"][-15:-7]
                        tree.add_to_source(x)
                        tree.rm_from_to_add(rd)
                for rd in rds_withdrawn:
                    print(rd)
                    tree.rm_from_source(rd)
                print(tree.nodes_to_add)
                print(tree.source_nodes)
                print("##########################################")

        plot_graph(mac, tree, labels)


def sessions():
    events = dict()
    for event_open in retrieve_opens()['hits']['hits']:
        if not (event_open['_source']['bgp_message']['open']['peer_one']['bgp_identifier'].startswith('10.10.') and
                event_open['_source']['bgp_message']['open']['peer_two']['bgp_identifier'].startswith('10.10.')):
            continue
        label = session_id(
            event_open['_source']['bgp_message']['open']['peer_one']['bgp_identifier'],
            event_open['_source']['bgp_message']['open']['peer_two']['bgp_identifier'])
        event = (dateutil.parser.isoparse(
            event_open['_source']['timestamp_received']), 'UP')
        events[label] = [event] + events[label] if label in events else [event]
    for event_cease in retrieve_ceases()['hits']['hits']:
        label = event_cease['_source']['bmp_header']['per_peer_header']['bgp_id']
        if not label.startswith('10.10.'):
            continue
        for key in events:
            if key.startswith(label + ' -') or key.endswith('- ' + label):
                events[key].append(
                    (dateutil.parser.isoparse(event_cease['_source']['timestamp_received']), 'DOWN {}'.format(key)))

    # ordering by timestamp
    events = {key: sorted(value, key=lambda item: item[0].timestamp())
              for key, value in events.items()}

    plt.gca().yaxis.set_major_formatter(mticker.FuncFormatter(sessions_status_ticks))
    # plt.xticks(numpy.arange(.0, 100, 5))
    plt.yticks(numpy.arange(.0, 2, 1))
    plt.gca().invert_yaxis()
    for label in events:
        if any(item.startswith('DOWN') for item in numpy.array(events[label])[:, 1]):
            # if label.startswith("10.10.10.1"):
            # print(len(events[label]))
            plt.plot(numpy.array(
                events[label])[:, 0], numpy.array(
                events[label])[:, 1], label=label)
    plt.legend(loc='best')
    plt.xlabel('Time')
    plt.ylabel('Session status')
    plt.gcf().autofmt_xdate()
    plt.show()


def sessions_status_ticks(val, pos):
    if pos == 0:
        return 'UP'
    elif pos == 1:
        return 'DOWN'
    return ''


def session_id(peer_one, peer_two='*'):
    return ' - '.join(sorted([peer_one, peer_two]))


def prefixes():
    events = dict()
    for event in retrieve_updates()['hits']['hits']:
        for update in event['_source']['bgp_message']['update']:
            if update['evpn_route_type'] != 'IP Prefix Route':
                continue
            if 'as_path' not in event['_source']['bgp_message']:
                continue
            if 'ip_prefix_length' not in update:
                update['ip_prefix_length'] = 32
            if ':' in update['ip_address']:
                # ignore IPv6
                continue
            if update['ip_prefix_length'] == 32:
                continue
            timestamp = prettify_timestamp(
                event['_source']['timestamp_received'])
            label = '{}:{}/{}'.format(update['route_distinguisher'],
                                      update['ip_address'], update['ip_prefix_length'])
            if label not in events:
                events[label] = list()
            events[label].append(
                (timestamp, event['_source']['bgp_message']['as_path'][-1]))

    plt.xticks(numpy.arange(.0, 1000, 75))
    plt.gca().invert_yaxis()
    for label in events:
        plt.scatter(numpy.array(events[label])[:, 0], numpy.array(
            events[label])[:, 1], label=label)
    plt.legend(loc='best')
    plt.xlabel('Time')
    plt.ylabel('Peer')
    plt.gcf().autofmt_xdate()
    plt.show()


def prettify_timestamp(timestamp):
    return dateutil.parser.isoparse(timestamp).strftime("%m-%d %H:%M:%S.%f")[:-3]


def plot_mac_mobility(mac_mm_counters, timestamps):
    plt.gca().xaxis.set_major_formatter(
        mdates.DateFormatter("%H:%M"))  # ("%Y-%m-%d %H:%M:%S"))
    locator = mdates.HourLocator()
    plt.gca().xaxis.set_major_locator(locator)
    plt.xticks(rotation='vertical')
    for k in mac_mm_counters.keys():
        if mac_mm_counters[k]:
            plt.plot(timestamps, mac_mm_counters[k], label=k)
    plt.legend(loc='upper left')
    plt.show()


def analyse_mac_mobility():
    updates = retrieve_updates()["hits"]["hits"]
    updates = sorted(updates, key=lambda d: dateutil.parser.isoparse(
        d["_source"]["timestamp_received"]).timestamp())
    mac_events = find_all_macs(updates)
    mac_mm_counters = {x: [] for x, _ in zip(mac_events, mac_events)}
    timestamps = []
    for u in updates:
        update = u["_source"]["bgp_message"]
        try:
            mac = update["update"][0]["mac_address"]
            for ec in update["extended_communities"]:
                if ec["type"] == "EVPN" and ec["subtype"] == "MAC Mobility":
                    mac_mm_counters[mac].append(ec["4_bytes_value"])
                    break
        except:
            pass
        timestamps.append(dateutil.parser.isoparse(
            u["_source"]["timestamp_received"]))
        for k in mac_mm_counters.keys():
            if mac_mm_counters[k]:
                while len(mac_mm_counters[k]) < len(timestamps):
                    mac_mm_counters[k].append(mac_mm_counters[k][-1])
    plot_mac_mobility(mac_mm_counters, timestamps)


if __name__ == "__main__":
    set_es_parameters()
    option = sys.argv[1]
    target = sys.argv[-1]
    if option == "--mac-analysis":
        mac = sys.argv[2]
        if len(sys.argv) > 3:
            tolerance = float(sys.argv[3])
        analyze_mac(mac)
    elif option == "--mac-flapping":
        if len(sys.argv) > 2:
            tolerance = float(sys.argv[2])
            print(tolerance)
        detect_flapping()
    elif option == "--sessions":
        sessions()
    elif option == "--prefixes":
        prefixes()
    elif option == "--mac-mobility":
        analyse_mac_mobility()
