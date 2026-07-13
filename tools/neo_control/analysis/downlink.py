#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
downlink.py — Escanea TODO el trafico (UP y DN) buscando frames DUML 0x55 con
CRC-8 de cabecera VALIDO, sin depender del offset del transporte. Sirve para
extraer las RESPUESTAS del dron (downlink type-1/2/3) y correlacionarlas con los
comandos del uplink: el candado del armado (token 0x03/0x20, handshake 0x03/0xf8).
"""
import sys, os, collections
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from djiudp import iter_pcap, parse_ip_udp, dji_header, DRONE_IP
from neo_udp import mb_crc8, mb_crc16

def mb_len(buf, i):
    if i+3 > len(buf) or buf[i] != 0x55: return None
    return buf[i+1] | ((buf[i+2] & 0x03) << 8)

def scan_frames(buf):
    """Devuelve todos los frames DUML 0x55 con CRC-8 de cabecera valido en buf."""
    out = []
    i = 0
    n = len(buf)
    while i < n:
        if buf[i] != 0x55:
            i += 1; continue
        ln = mb_len(buf, i)
        if not ln or ln < 13 or i+ln > n:
            i += 1; continue
        fr = buf[i:i+ln]
        if mb_crc8(fr[:3]) != fr[3]:      # CRC-8 de la cabecera (bytes 0..2)
            i += 1; continue
        out.append((i, fr))
        i += ln
    return out

def frame_fields(fr):
    ln = mb_len(fr, 0)
    return dict(ln=ln, snd=fr[4], rcv=fr[5], dseq=fr[6]|(fr[7]<<8),
                attr=fr[8], cset=fr[9], cid=fr[10], payload=fr[11:ln-2],
                crc16_ok=(mb_crc16(fr[:ln-2]) == (fr[ln-2]|(fr[ln-1]<<8))))

def walk(path):
    """(ts, dir, ptype, seq, offset, frame_fields) por cada DUML CRC-valido."""
    for ts, ip in iter_pcap(path):
        r = parse_ip_udp(ip)
        if not r: continue
        src, dst, sp, dp, pl = r
        if 9003 not in (sp, dp): continue
        h = dji_header(pl)
        if not h: continue
        d = "DN" if src == DRONE_IP else "UP"
        for off, fr in scan_frames(pl):
            m = frame_fields(fr)
            m["raw"] = fr
            yield ts, d, h["ptype"], h["seq"], off, m

def census(path):
    print("="*78); print("DUML por CRC-8 (UP+DN):", path)
    t0 = None
    by = collections.Counter(); first = {}; ptypes = collections.Counter()
    for ts, d, pt, seq, off, m in walk(path):
        if t0 is None: t0 = ts
        k = (d, m["cset"], m["cid"])
        by[k] += 1
        ptypes[(d, pt)] += 1
        if k not in first: first[k] = (ts-t0, pt, off)
    print("\n-- (dir, ptype) portadores de DUML --")
    for (d, pt), n in sorted(ptypes.items()):
        print(f"  {d} type-0x{pt:02x}: {n}")
    print("\n-- DN (respuestas del dron): (cmd_set,cmd_id) : n | t+ | ptype | off --")
    for (d, cs, ci), n in sorted(by.items(), key=lambda x:-x[1]):
        if d != "DN": continue
        rel, pt, off = first[(d,cs,ci)]
        print(f"  DN 0x{cs:02x}/0x{ci:02x}: {n:5d}  t+{rel:7.2f}s  type-0x{pt:02x}  off={off}")

if __name__ == "__main__":
    census(sys.argv[1])
