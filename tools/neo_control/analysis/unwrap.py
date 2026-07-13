#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
unwrap.py — Des-envuelve el contenedor 0x51/0x01 ("transmision transparente") del
Neo y saca el CENSO REAL de comandos DUML internos + timeline del despegue.

Estructura descubierta (Octava prueba):
  type-5 UDP payload -> [cabecera 8 + flowcontrol hasta 0x14] -> frame(s) MB
  Frame externo 0x51/0x01:
     55 len ver crc8 | snd=3b rcv=e9 | dseq2(2) | attr=00 | 51 01 |
     <FRAME DUML INTERNO completo> | cola(~21B: 0099d4ac02 <ctr4> ffffffff 0182 00..) | crc16
  El FRAME DUML INTERNO es el comando real (p.ej. 02 03 .. 40 03 da = TAKEOFF).
"""
import sys, collections
from djiudp import iter_pcap, parse_ip_udp, dji_header, DRONE_IP

def mb_len(fr, i=0):
    """Longitud declarada de un frame MB en offset i (o None)."""
    if i+3 > len(fr) or fr[i] != 0x55: return None
    return fr[i+1] | ((fr[i+2] & 0x03) << 8)

def parse_mb(fr):
    if len(fr) < 13 or fr[0] != 0x55: return None
    ln = mb_len(fr)
    return dict(ln=ln, snd=fr[4], rcv=fr[5], dseq=fr[6]|(fr[7]<<8),
                attr=fr[8], cset=fr[9], cid=fr[10], payload=fr[11:ln-2], raw=fr[:ln])

def unwrap(fr):
    """Si fr es un contenedor 0x51/0x01, devuelve el frame DUML interno; si no, fr."""
    m = parse_mb(fr)
    if not m: return None
    if m["cset"] == 0x51 and m["cid"] == 0x01:
        inner = fr[11:]                       # el frame interno arranca tras 51 01
        il = mb_len(inner)
        if il and il <= len(inner):
            return parse_mb(inner[:il])
    return m

def walk_frames(path):
    """Genera (ts, dir, seq, frame_bytes) por cada frame MB de nivel superior."""
    for ts, ip in iter_pcap(path):
        r = parse_ip_udp(ip)
        if not r: continue
        src, dst, sp, dp, pl = r
        if 9003 not in (sp, dp): continue
        h = dji_header(pl)
        if not h or h["ptype"] != 0x05: continue
        up = (dst == DRONE_IP)
        blob = pl[0x14:]
        i = 0
        while i+3 <= len(blob) and blob[i] == 0x55:
            ln = mb_len(blob, i)
            if not ln or i+ln > len(blob): break
            yield ts, ("UP" if up else "DN"), h["seq"], blob[i:i+ln]
            i += ln

def census(path):
    print("="*78); print("CENSO REAL (interno) :", path)
    t0 = None
    cnt = collections.Counter(); first = {}
    for ts, d, seq, fr in walk_frames(path):
        if t0 is None: t0 = ts
        m = unwrap(fr)
        if not m: continue
        key = (d, m["cset"], m["cid"])
        cnt[key] += 1
        if key not in first: first[key] = ts - t0
    for (d, cs, ci), n in sorted(cnt.items(), key=lambda x: -x[1]):
        print(f"  {d} set=0x{cs:02x} id=0x{ci:02x}: {n:6d}   t+{first[(d,cs,ci)]:7.2f}s")

def find(path, cset, cid, ctx=0.0):
    print("="*78); print(f"BUSCAR interno set=0x{cset:02x} id=0x{cid:02x} :", path)
    t0 = None
    for ts, d, seq, fr in walk_frames(path):
        if t0 is None: t0 = ts
        outer = parse_mb(fr)
        wrapped = bool(outer and outer["cset"] == 0x51 and outer["cid"] == 0x01)
        m = unwrap(fr)
        if not m: continue
        if m["cset"] == cset and m["cid"] == cid:
            tag = "WRAP(51/01)" if wrapped else "BARE"
            print(f"  t+{ts-t0:7.3f} {d} seq=0x{seq:04x} {tag:11s} snd=0x{m['snd']:02x} rcv=0x{m['rcv']:02x} "
                  f"attr=0x{m['attr']:02x} dseq=0x{m['dseq']:04x} pl={m['payload'].hex()}")

if __name__ == "__main__":
    path = sys.argv[1]
    if len(sys.argv) >= 4:
        find(path, int(sys.argv[2],16), int(sys.argv[3],16))
    else:
        census(path)
