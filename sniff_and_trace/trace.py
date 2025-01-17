import ipaddress
import json
import logging
import math
import os
import socket
import urllib.request
from typing import Optional, Tuple, Dict, Set

import plotly.graph_objects as go
from scapy.layers.inet import traceroute
from scapy.layers.inet6 import traceroute6

marker_size = 10
max_ttl_traceroute = 32

cache_name = "ip_lat_lon_cache.csv"


class Trace:
    def __init__(self):
        self.ip_locations: Dict[str, Tuple[float, float]] = {}
        self.blacklisted_ips: Set[str] = set()

    def read_from_file(self) -> None:
        if os.path.exists(cache_name):
            try:
                with open(cache_name, 'r') as cache:
                    cache.readline()  # header
                    for line in cache.readlines():
                        ip, lat, lon = line.split(',')
                        self.ip_locations[ip] = float(lat), float(lon)
            except Exception as e:
                logging.error(f'Unable to load cache: {e}')

    def write_to_file(self) -> None:
        try:
            with open(cache_name, 'w') as cache:
                cache.write('ip,latitude,longitude\n')
                for ip, (lat, lon) in self.ip_locations.items():
                    cache.write(f'{ip}, {lat}, {lon}\n')
        except Exception as e:
            logging.error(f'Unable to write to cache: {e}')

    def get_lat_lon(self, ip_addr: str) -> Optional[Tuple[float, float]]:
        if ip_addr in self.blacklisted_ips:
            return None
        elif ip_addr in self.ip_locations:
            return self.ip_locations[ip_addr]

        try:
            with urllib.request.urlopen(f'https://geolocation-db.com/json/{ip_addr}') as url:
                json_data = json.loads(url.read().decode())
                if 'latitude' not in json_data or 'longitude' not in json_data:
                    self.blacklisted_ips.add(ip_addr)
                    return None

                lat, lon = json_data['latitude'], json_data['longitude']
                if lat == 'Not found' or lon == 'Not found' or lat is None or lon is None:
                    self.blacklisted_ips.add(ip_addr)
                    return None
                else:
                    self.ip_locations[ip_addr] = lat, lon
                    return lat, lon
        except Exception as e:
            logging.warning(f'Unable to determine location of {ip_addr}: {e}')
            return None

    def trace(self, ip: str, hits: int, byte_count: int, timeout: int, display_name: bool) -> go.Scattergeo:
        if isinstance(ipaddress.ip_address(ip), ipaddress.IPv6Address):
            ans, err = traceroute6(ip, maxttl=max_ttl_traceroute, dport=53, verbose=False, timeout=timeout)
        else:
            ans, err = traceroute(ip, maxttl=max_ttl_traceroute, dport=53, verbose=False, timeout=timeout)

        lats, lons, text, received = [], [], [], set()
        msg = f'Route to {ip}: '
        count = 1
        for sent_ip, received_ip in ans.res:
            res = self.get_lat_lon(received_ip.src)
            if res is not None:
                lat, lon = res[0], res[1]
                lats += [lat]
                lons += [lon]
                text += [f'hop {count}: {received_ip.src if display_name else ""}']
                msg += f'{sent_ip.dst} [{lat}, {lon}], '
                received.add(received_ip.src)
                count += 1

        if ip not in received:
            res = self.get_lat_lon(ip)
            if res is not None:
                lat, lon = res[0], res[1]
                lats += [lat]
                lons += [lon]
                text += [f'hop {count}: {ip}']

        logging.info(msg)
        mode = 'markers' if len(lats) == 1 else 'markers+lines'

        if display_name:
            try:
                name, _, _ = socket.gethostbyaddr(ip)
                host_addr = f'{name} | '
            except Exception as e:
                logging.warning(f'Failed to get hostname of {ip}: {e}')
                host_addr = ''
            name = f'{host_addr} {ip}<br>'
        else:
            name = ''

        return go.Scattergeo(mode=mode, lon=lons, lat=lats, text=text,
                             name=f'{name}{hits} packets, {byte_count} bytes',
                             line={'width': int(math.log(byte_count)) / 2},
                             marker={'size': marker_size, 'symbol': 'square'})
