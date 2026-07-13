#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
duml_timeline.py — Extrae y clasifica los frames DUML (0x55...) que la app envia
dentro de los paquetes type-5 (uplink app->dron), en orden cronologico.

Objetivo: descubrir la SECUENCIA REAL de despegue del DJI Neo capturada con la app
(Octava prueba), para copiarla byte a byte en lugar de inferirla.

Un paquete type-5 puede acarrear >1 frame MB concatenados tras el offset 0x14.
Cada frame MB: 55 len ver crc8 snd rcv seq(2) attr set id payload crc16(2).
"""
import struct, sys, collections
from djiudp import iter_pcap, parse_ip_udp, dji_header, DRONE_IP

def split_mb(buf):
    """Divide el blob (>=1 frames MB concatenados) en frames individuales."""
    out = []
    i = 0
    while i + 4 <= len(buf):
        if buf[i] != 0x55:
            break
        ln = buf[i+1] | ((buf[i+2] & 0x03) << 8)   # len en 10 bits (byte1 + 2 bits de byte2)
        if ln < 11 or i + ln > len(buf):
            break
        out.append(buf[i:i+ln])
        i += ln
    return out, buf[i:]

def parse_mb(fr):
    """Devuelve dict con los campos de un frame MB/DUML."""
    if len(fr) < 13 or fr[0] != 0x55:
        return None
    ln = fr[1] | ((fr[2] & 0x03) << 8)
    snd, rcv = fr[4], fr[5]
    dseq = fr[6] | (fr[7] << 8)
    attr = fr[8]
    cset = fr[9]
    cid = fr[10]
    payload = fr[11:ln-2]
    return dict(ln=ln, snd=snd, rcv=rcv, dseq=dseq, attr=attr,
                cset=cset, cid=cid, payload=payload, raw=fr)

def walk(path):
    """Genera (ts, dir, seq, [frames MB]) para cada paquete type-5 up/down en 9003."""
    for ts, ip in iter_pcap(path):
        r = parse_ip_udp(ip)
        if not r: continue
        src, dst, sp, dp, pl = r
        if 9003 not in (sp, dp): continue
        h = dji_header(pl)
        if not h or h["ptype"] != 0x05: continue
        up = (dst == DRONE_IP)
        blob = pl[0x14:]
        frames, _ = split_mb(blob)
        mbs = [parse_mb(f) for f in frames]
        mbs = [m for m in mbs if m]
        yield ts, ("UP" if up else "DN"), h["seq"], mbs

def summarize(path):
    print("=" * 78); print("PCAP:", path)
    cmd_count = collections.Counter()          # (dir, cset, cid) -> n
    first_seen = {}                            # (dir,cset,cid) -> (ts, raw hex)
    t5_up = 0
    t0 = None
    timeline = []                              # (ts, dir, cset, cid, plhex)
    for ts, d, seq, mbs in walk(path):
        if t0 is None: t0 = ts
        if d == "UP": t5_up += 1
        for m in mbs:
            key = (d, m["cset"], m["cid"])
            cmd_count[key] += 1
            if key not in first_seen:
                first_seen[key] = (ts - t0, m["raw"].hex(), m["attr"])
            timeline.append((ts - t0, d, m["cset"], m["cid"], m["payload"].hex()))

    print("total paquetes type-5 UP:", t5_up)
    print("\n-- comandos DUML por (dir, cmd_set, cmd_id) : conteo | primera vez (s) | attr --")
    for (d, cs, ci), n in sorted(cmd_count.items(), key=lambda x: -x[1]):
        rel, rawhex, attr = first_seen[(d, cs, ci)]
        print(f"  {d} set=0x{cs:02x} id=0x{ci:02x}: {n:6d}   t+{rel:7.2f}s  attr=0x{attr:02x}")
    return timeline, first_seen

if __name__ == "__main__":
    for p in sys.argv[1:]:
        summarize(p)
