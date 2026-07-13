#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Timeline de eventos DUML discretos + decodificacion del stream 0x51/0x01."""
import sys, collections
from djiudp import iter_pcap, parse_ip_udp, dji_header, DRONE_IP
from duml_timeline import walk

# comandos de alta frecuencia (streams) que NO queremos ver uno por uno
STREAM = {(0x51,0x01),(0x01,0x0a),(0x00,0x01)}

def events(path, tmin=None, tmax=None):
    print("="*78); print("EVENTOS DISCRETOS:", path)
    t0 = None
    for ts, d, seq, mbs in walk(path):
        if t0 is None: t0 = ts
        rel = ts - t0
        if tmin is not None and rel < tmin: continue
        if tmax is not None and rel > tmax: continue
        for m in mbs:
            if (m["cset"], m["cid"]) in STREAM: continue
            print(f"  t+{rel:7.2f} {d} set=0x{m['cset']:02x} id=0x{m['cid']:02x} "
                  f"attr=0x{m['attr']:02x} dseq=0x{m['dseq']:04x} pl={m['payload'].hex()}")

def stream_profile(path, cset, cid, step=0.5):
    """Muestra como evoluciona el payload de un stream (primer byte-diferencia) en el tiempo."""
    print("="*78); print(f"PERFIL STREAM set=0x{cset:02x} id=0x{cid:02x}:", path)
    t0 = None
    last = None
    buckets = collections.OrderedDict()
    for ts, d, seq, mbs in walk(path):
        if d != "UP": continue
        if t0 is None: t0 = ts
        rel = ts - t0
        for m in mbs:
            if (m["cset"], m["cid"]) != (cset, cid): continue
            b = int(rel/step)*step
            buckets.setdefault(b, []).append(m["payload"].hex())
    for b, pls in buckets.items():
        # muestra el primero y si cambia dentro del bucket
        uniq = []
        for p in pls:
            if not uniq or uniq[-1] != p: uniq.append(p)
        show = uniq[0] if len(uniq)==1 else f"{uniq[0]} ..{len(uniq)} variantes.. {uniq[-1]}"
        print(f"  t+{b:6.1f}s (n={len(pls):3d}) {show}")

if __name__ == "__main__":
    path = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else "events"
    if mode == "events":
        tmin = float(sys.argv[3]) if len(sys.argv) > 3 else None
        tmax = float(sys.argv[4]) if len(sys.argv) > 4 else None
        events(path, tmin, tmax)
    elif mode == "stream":
        cset = int(sys.argv[3], 16); cid = int(sys.argv[4], 16)
        stream_profile(path, cset, cid)
