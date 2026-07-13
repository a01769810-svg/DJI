#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Parser del protocolo UDP propietario DJI (hipotesis samuelsadok/dji_protocol)
contra los PCAPs del Neo. Linktype 101 (RAW IP), pcap clasico LE.

Header DJI (todos los paquetes), offsets dentro del payload UDP:
  0x00-01  len (bits14:0) | bit15=1
  0x02-03  session id
  0x04-05  sequence number (!=0 solo en tipos 0x02,0x03,0x05)
  0x06     packet type (0x00..0x06)
  0x07     XOR de los primeros 7 bytes
"""
import struct, sys, collections

def iter_pcap(path):
    with open(path, "rb") as f:
        gh = f.read(24)
        if gh[:4] != b"\xd4\xc3\xb2\xa1":
            raise SystemExit("magic inesperado: %s" % gh[:4].hex())
        linktype = struct.unpack("<I", gh[20:24])[0]
        assert linktype == 101, linktype
        while True:
            rh = f.read(16)
            if len(rh) < 16: break
            ts_sec, ts_usec, incl, orig = struct.unpack("<IIII", rh)
            data = f.read(incl)
            if len(data) < incl: break
            yield ts_sec + ts_usec/1e6, data

def parse_ip_udp(ip):
    if len(ip) < 20 or (ip[0] >> 4) != 4:
        return None
    ihl = (ip[0] & 0x0f) * 4
    if ip[9] != 17:  # UDP
        return None
    src = ".".join(str(b) for b in ip[12:16])
    dst = ".".join(str(b) for b in ip[16:20])
    udp = ip[ihl:]
    if len(udp) < 8: return None
    sport, dport, ulen, _ = struct.unpack("!HHHH", udp[:8])
    payload = udp[8:]
    return src, dst, sport, dport, payload

def dji_header(p):
    if len(p) < 8: return None
    length = (p[0] | (p[1] << 8)) & 0x7fff
    bit15 = (p[1] >> 7) & 1
    sess = p[2] | (p[3] << 8)
    seq = p[4] | (p[5] << 8)
    ptype = p[6]
    xorb = p[7]
    xcalc = 0
    for b in p[:7]:
        xcalc ^= b
    return dict(length=length, bit15=bit15, sess=sess, seq=seq,
               ptype=ptype, xorb=xorb, xcalc=xcalc, xor_ok=(xorb == xcalc),
               len_ok=(length == len(p)))

DRONE_IP = "192.168.2.1"

def analyze(path, limit=None):
    n = 0
    by_type = collections.Counter()
    xor_fail = collections.Counter()   # ptype -> count of XOR mismatches
    xor_total = collections.Counter()
    len_fail = collections.Counter()
    dir_type = collections.Counter()   # (dir, ptype)
    up_seq = collections.defaultdict(list)   # ptype -> list of seq (app->drone)
    down_seq = collections.defaultdict(list)
    sessions = collections.Counter()
    first_hello = {}
    for ts, ip in iter_pcap(path):
        r = parse_ip_udp(ip)
        if not r: continue
        src, dst, sp, dp, pl = r
        if 9003 not in (sp, dp): continue
        h = dji_header(pl)
        if not h: continue
        up = (dst == DRONE_IP)   # app/us -> drone
        d = "UP" if up else "DN"
        by_type[h["ptype"]] += 1
        dir_type[(d, h["ptype"])] += 1
        xor_total[h["ptype"]] += 1
        if not h["xor_ok"]: xor_fail[h["ptype"]] += 1
        if not h["len_ok"]: len_fail[h["ptype"]] += 1
        sessions[h["sess"]] += 1
        if h["ptype"] == 0x00 and d not in first_hello:
            seed = (pl[8] | (pl[9] << 8)) if len(pl) >= 10 else None
            first_hello[d] = (pl[:16].hex(), seed)
        (up_seq if up else down_seq)[h["ptype"]].append((ts, h["seq"]))
        n += 1
        if limit and n >= limit: break
    return dict(n=n, by_type=by_type, xor_fail=xor_fail, xor_total=xor_total,
               len_fail=len_fail, dir_type=dir_type, up_seq=up_seq,
               down_seq=down_seq, sessions=sessions, first_hello=first_hello)

def report(path, limit=None):
    print("="*70)
    print("PCAP:", path)
    r = analyze(path, limit)
    print("paquetes 9003 analizados:", r["n"])
    print("sessions (id->count):", {hex(k): v for k, v in r["sessions"].most_common(5)})
    print("first hello por dir (hex16, seed@8-9):",
          {k: (v[0], hex(v[1]) if v[1] is not None else None) for k, v in r["first_hello"].items()})
    print("\n-- por (direccion, tipo) --")
    for (d, t), c in sorted(r["dir_type"].items()):
        print(f"  {d} type 0x{t:02x}: {c}")
    print("\n-- validacion XOR offset7 (fallos/total por tipo) --")
    for t in sorted(r["xor_total"]):
        print(f"  type 0x{t:02x}: {r['xor_fail'][t]} fallos / {r['xor_total'][t]}"
              f"  ({'TODOS OK' if r['xor_fail'][t]==0 else 'HAY FALLOS'})")
    print("\n-- validacion length offset0-1 (fallos por tipo) --")
    for t in sorted(r["xor_total"]):
        print(f"  type 0x{t:02x}: {r['len_fail'][t]} fallos de longitud")
    # progresion de seq del uplink type-5 (comandos)
    for label, store in (("UP", r["up_seq"]), ("DN", r["down_seq"])):
        for t in (0x02, 0x03, 0x05):
            seqs = store.get(t)
            if not seqs or len(seqs) < 3: continue
            vals = [s for _, s in seqs[:12]]
            diffs = [ (vals[i+1]-vals[i]) & 0xffff for i in range(len(vals)-1)]
            print(f"\n-- {label} type 0x{t:02x} seq (primeros 12): {[hex(v) for v in vals]}")
            print(f"   pasos: {diffs}")
    return r

if __name__ == "__main__":
    paths = sys.argv[1:]
    for p in paths:
        report(p)
