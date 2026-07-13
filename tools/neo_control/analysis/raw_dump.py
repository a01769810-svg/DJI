#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Volcado CRUDO de paquetes type-5 UP en una ventana de tiempo, sin interpretar MB."""
import sys
from djiudp import iter_pcap, parse_ip_udp, dji_header, DRONE_IP

def dump(path, tmin, tmax, direction="UP"):
    print("="*78); print(f"RAW type-5 {direction} [{tmin}..{tmax}]s :", path)
    t0 = None
    for ts, ip in iter_pcap(path):
        r = parse_ip_udp(ip)
        if not r: continue
        src, dst, sp, dp, pl = r
        if 9003 not in (sp, dp): continue
        h = dji_header(pl)
        if not h or h["ptype"] != 0x05: continue
        up = (dst == DRONE_IP)
        if (direction == "UP") != up: continue
        if t0 is None: t0 = ts
        rel = ts - t0
        if rel < tmin or rel > tmax: continue
        mb = pl[0x14:]           # region MB tras cabecera+flowcontrol
        print(f"t+{rel:7.3f} seq=0x{h['seq']:04x} len={h['length']} MB[{len(mb)}]={mb.hex()}")

if __name__ == "__main__":
    path = sys.argv[1]
    tmin = float(sys.argv[2]); tmax = float(sys.argv[3])
    direction = sys.argv[4] if len(sys.argv) > 4 else "UP"
    dump(path, tmin, tmax, direction)
