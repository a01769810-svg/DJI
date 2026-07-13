#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Valida el wrapper CORREGIDO reconstruyendo byte-a-byte los paquetes type-5
reales de la app (Quinta). Si coincide, el fix es correcto.

Wrapper type-5 corregido (20 bytes de cabecera+flow-control, luego payload MB):
  0x00-01 len|0x8000
  0x02-03 session
  0x04-05 seq  (seed+8, +8 por paquete)
  0x06    0x05
  0x07    XOR(bytes 0..6)
  0x08-09 t5 send window start
  0x0a-0b t5 send window end
  0x0c-0d resend state1 (0)
  0x0e-0f resend state2 (0)
  0x10    contador type-5 (1,2,3,...)
  0x11-13 01 00 00
  0x14+   payload DJI MB (0x55...)
"""
import sys
from djiudp import iter_pcap, parse_ip_udp, dji_header, DRONE_IP

def build_t5(session, seq, send_start, send_end, ctr, mb):
    body_len = 0x14 + len(mb)
    hdr = bytearray(0x14)
    hdr[0] = body_len & 0xff
    hdr[1] = 0x80 | ((body_len >> 8) & 0x7f)
    hdr[2] = session & 0xff
    hdr[3] = (session >> 8) & 0xff
    hdr[4] = seq & 0xff
    hdr[5] = (seq >> 8) & 0xff
    hdr[6] = 0x05
    x = 0
    for b in hdr[:7]:
        x ^= b
    hdr[7] = x
    hdr[8] = send_start & 0xff;  hdr[9]  = (send_start >> 8) & 0xff
    hdr[0x0a] = send_end & 0xff; hdr[0x0b] = (send_end >> 8) & 0xff
    # 0x0c..0x0f resend states = 0
    hdr[0x10] = ctr & 0xff
    hdr[0x11] = 0x01; hdr[0x12] = 0x00; hdr[0x13] = 0x00
    return bytes(hdr) + mb

# Extrae los primeros N type-5 de la app (Quinta) y reconstruyelos.
def validate(path, n=8):
    pkts = []
    for ts, ip in iter_pcap(path):
        r = parse_ip_udp(ip)
        if not r: continue
        src, dst, sp, dp, pl = r
        if dst != DRONE_IP or 9003 not in (sp, dp): continue
        h = dji_header(pl)
        if h and h["ptype"] == 0x05:
            pkts.append(pl)
            if len(pkts) >= n: break

    print("Validando", len(pkts), "paquetes type-5 de", path)
    ok = 0
    for p in pkts:
        session = p[2] | (p[3] << 8)
        seq = p[4] | (p[5] << 8)
        ss = p[8] | (p[9] << 8)
        se = p[0x0a] | (p[0x0b] << 8)
        ctr = p[0x10]
        mb = p[0x14:]
        rebuilt = build_t5(session, seq, ss, se, ctr, mb)
        match = rebuilt == p
        ok += match
        if not match:
            # muestra primer byte divergente
            for i,(a,b) in enumerate(zip(rebuilt,p)):
                if a!=b:
                    print(f"  DIFF seq=0x{seq:04x} en offset 0x{i:02x}: build={a:02x} real={b:02x}")
                    break
        else:
            print(f"  seq=0x{seq:04x} ctr={ctr}: MATCH byte-a-byte ({len(p)} B)")
    print(f"\nRESULTADO: {ok}/{len(pkts)} reconstruidos identicos al trafico real de la app")

if __name__ == "__main__":
    validate(sys.argv[1] if len(sys.argv)>1 else "Quinta prueba.pcap")
