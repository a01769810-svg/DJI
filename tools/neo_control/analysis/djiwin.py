#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Decodifica los campos de flow-control (ventanas type-5) app vs emisor propio."""
import sys
from djiudp import iter_pcap, parse_ip_udp, dji_header, DRONE_IP

def u16(p, o): return p[o] | (p[o+1] << 8)

def dump(path, n_t5=6, n_t1=8):
    print("="*70); print("PCAP:", path)
    up_t5 = []; dn_t1 = []
    for ts, ip in iter_pcap(path):
        r = parse_ip_udp(ip)
        if not r: continue
        src, dst, sp, dp, pl = r
        if 9003 not in (sp, dp): continue
        h = dji_header(pl)
        if not h: continue
        up = (dst == DRONE_IP)
        if up and h["ptype"] == 0x05 and len(up_t5) < n_t5:
            up_t5.append((ts, pl))
        if (not up) and h["ptype"] == 0x01 and len(dn_t1) < n_t1:
            dn_t1.append((ts, pl))
        if len(up_t5) >= n_t5 and len(dn_t1) >= n_t1: break

    print("\n### UP type-5 (comando app->dron) — cabecera + campos flow-control")
    for ts, p in up_t5:
        h = dji_header(p)
        print(f"  seq=0x{h['seq']:04x} xor_ok={h['xor_ok']} "
              f"t5_send_start=0x{u16(p,8):04x} t5_send_end=0x{u16(p,0x0a):04x} "
              f"resend1=0x{u16(p,0x0c):04x} resend2=0x{u16(p,0x0e):04x} "
              f"ctr=0x{p[0x10]:02x} tag={p[0x11:0x14].hex()} mb={p[0x14:0x14+6].hex()}...")
    print("\n### DN type-1 (telemetria dron->app) — ventana RX type-5 que el dron espera")
    for ts, p in dn_t1:
        # per doc: 0x18-19 type5 recv window start, 0x1a-1b type5 recv window end
        print(f"  t2_send=[0x{u16(p,8):04x}..0x{u16(p,0x0a):04x}] "
              f"t3_send=[0x{u16(p,0x10):04x}..0x{u16(p,0x12):04x}] "
              f"T5_RECV_WINDOW=[0x{u16(p,0x18):04x}..0x{u16(p,0x1a):04x}] "
              f"resendlist@1c={p[0x1c:0x1e].hex()}")

if __name__ == "__main__":
    for p in sys.argv[1:]:
        dump(p)
