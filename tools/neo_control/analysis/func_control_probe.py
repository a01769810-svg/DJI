#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
func_control_probe.py — Analisis adversarial: separar CAUSA de CORRELACION en el
despegue del Neo. Cruza el mapa historico DJI P3 (ctomichael/fpv_live) contra
Quinta/Octava.

Escaneo RECURSIVO de DUML: por cada paquete UDP 9003, encuentra todo frame 0x55
con CRC-8 de cabecera valido, y si es contenedor 0x51/0x01 recurre en su payload
(capta bare + envuelto + anidado, uplink + downlink, a cualquier profundidad).

Hipotesis historicas a validar:
  0x2a FunctionControl (1B: 01 AUTO_FLY,02 AUTO_LANDING,07 START_MOTOR,
                        08 STOP_MOTOR,22 PRECISION_TAKE_OFF)
  0xda Detection (sub 05 = SetSwitch + uint32)  <- NUESTRO "takeoff"
  0x20 SendGpsToFlyc | 0x34 GetPlaneName | 0x3c GetFsAction
  0xf8 GetParamsByHash | 0xd7 GetPushFlightRecord
"""
import sys, os, collections
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from djiudp import iter_pcap, parse_ip_udp, dji_header, DRONE_IP
from neo_udp import mb_crc8, mb_crc16

def mb_len(buf, i=0):
    if i+3 > len(buf) or buf[i] != 0x55: return None
    return buf[i+1] | ((buf[i+2] & 0x03) << 8)

def fields(fr):
    ln = mb_len(fr)
    if not ln or ln < 13 or ln > len(fr): return None
    return dict(ln=ln, snd=fr[4], rcv=fr[5], dseq=fr[6]|(fr[7]<<8),
                attr=fr[8], cset=fr[9], cid=fr[10], payload=fr[11:ln-2],
                crc16_ok=(mb_crc16(fr[:ln-2]) == (fr[ln-2]|(fr[ln-1]<<8))))

def scan_duml(buf, depth=0):
    """Genera (frame_fields, wrapped_depth) recursivamente."""
    i = 0
    n = len(buf)
    while i < n:
        if buf[i] != 0x55:
            i += 1; continue
        ln = mb_len(buf, i)
        if not ln or ln < 13 or i+ln > n:
            i += 1; continue
        fr = buf[i:i+ln]
        if mb_crc8(fr[:3]) != fr[3]:
            i += 1; continue
        m = fields(fr)
        if m:
            yield m, depth
            if m["cset"] == 0x51 and m["cid"] == 0x01:
                yield from scan_duml(m["payload"], depth+1)
        i += ln

def walk_all(path):
    """(ts_rel, dir, frame_fields, depth) por cada DUML en cualquier capa."""
    t0 = None
    for ts, ip in iter_pcap(path):
        r = parse_ip_udp(ip)
        if not r: continue
        src, dst, sp, dp, pl = r
        if 9003 not in (sp, dp): continue
        if t0 is None: t0 = ts
        d = "DN" if src == DRONE_IP else "UP"
        for m, depth in scan_duml(pl):
            yield ts - t0, d, m, depth

FUNC = {0x01:"AUTO_FLY",0x02:"AUTO_LANDING",0x07:"START_MOTOR",
        0x08:"STOP_MOTOR",0x22:"PRECISION_TAKE_OFF"}

def analyze(path):
    print("="*80); print("PROBE:", os.path.basename(path))
    rows = list(walk_all(path))

    # --- onset markers (proxy del despegue fisico) ---
    def first(pred):
        for rel, d, m, depth in rows:
            if pred(rel, d, m, depth): return rel
        return None
    big_video = first(lambda rel,d,m,dep: d=="DN" and m["ln"]>=1000)   # frames grandes DN ~ video
    first_stick = first(lambda rel,d,m,dep: d=="UP" and m["cset"]==0x01 and m["cid"]==0x0a)
    dn_d7 = first(lambda rel,d,m,dep: d=="DN" and m["cset"]==0x03 and m["cid"]==0xd7)
    up_da05 = first(lambda rel,d,m,dep: d=="UP" and m["cset"]==0x03 and m["cid"]==0xda and m["payload"][:1]==b"\x05")
    print("\n-- ONSETS (proxy despegue) --")
    print(f"  primer UP 0x03/0xda:05 (nuestro 'takeoff') : t+{up_da05}")
    print(f"  primer UP sticks 0x01/0x0a                 : t+{first_stick}")
    print(f"  primer DN grande (>=1000B, ~video)         : t+{big_video}")
    print(f"  primer DN 0x03/0xd7 (push flight record)   : t+{dn_d7}")

    # --- 0x03/0x2a FunctionControl: EXHAUSTIVO ---
    print("\n-- 0x03/0x2a FunctionControl (TODOS: up/dn, bare/wrap/anidado) --")
    n2a = 0
    for rel, d, m, depth in rows:
        if m["cset"] == 0x03 and m["cid"] == 0x2a:
            n2a += 1
            p = m["payload"]
            sub = p[0] if p else None
            name = FUNC.get(sub, "?")
            loc = "bare" if depth == 0 else f"wrap x{depth}"
            print(f"  t+{rel:7.3f} {d} {loc:8s} snd=0x{m['snd']:02x} rcv=0x{m['rcv']:02x} "
                  f"pl={p.hex()}  sub=0x{sub:02x}({name})" if sub is not None
                  else f"  t+{rel:7.3f} {d} {loc:8s} pl=<vacio>")
    if n2a == 0:
        print("  *** NINGUN 0x03/0x2a en toda la captura ***")

    # --- 0x03/0xda: todos los subcomandos y su direccion ---
    print("\n-- 0x03/0xda (subcomando por 1er byte): conteo up/dn + primer t --")
    da = collections.Counter(); da_first = {}
    for rel, d, m, depth in rows:
        if m["cset"] == 0x03 and m["cid"] == 0xda:
            sub = m["payload"][:1].hex() if m["payload"] else ""
            k = (d, sub)
            da[k] += 1
            if k not in da_first: da_first[k] = rel
    for (d, sub), c in sorted(da.items()):
        print(f"  {d} sub={sub or '(vacio)':10s} n={c:4d}  primer t+{da_first[(d,sub)]:.3f}")

    # --- busqueda directa de los payloads FunctionControl en CUALQUIER cmd_id ---
    print("\n-- payloads FunctionControl (01/02/07/08/22) en 0x03/* de 1 byte --")
    hits = 0
    for rel, d, m, depth in rows:
        if m["cset"] == 0x03 and len(m["payload"]) == 1 and m["payload"][0] in FUNC:
            hits += 1
            print(f"  t+{rel:7.3f} {d} 0x03/0x{m['cid']:02x} pl={m['payload'].hex()} "
                  f"({FUNC[m['payload'][0]]})")
    if not hits:
        print("  (ninguno de 1 byte exacto)")

if __name__ == "__main__":
    for p in (sys.argv[1:] or ["../../../Quinta prueba.pcap", "../../../Octava prueba.pcap"]):
        analyze(p)
