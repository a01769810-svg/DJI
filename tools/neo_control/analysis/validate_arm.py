#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate_arm.py — Valida que los builders del armado (neo_udp.py) reproducen
BYTE A BYTE los frames DUML reales de la app (Quinta/Octava), antes de tocar
hardware. Cubre: reconstruccion generica MB (CRC-8/CRC-16) + cada builder
semantico (autoridad 0x03/0x20, heartbeat 0x03/0xd7, lote 0x03/0xf8, modo
0x03/0xf9, despegue 0x03/0xda, rafaga 0x03/0x34, 0x03/0x3c, 0x0d/0x03).

PRIVACIDAD: la autoridad var-03 lleva la coordenada GPS del usuario. Este script
extrae lat/lon del frame real SOLO para alimentar el builder y comparar; NUNCA
los imprime. Solo reporta MATCH/DIFF.
"""
import sys, os, struct, collections
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from unwrap import walk_frames, unwrap, parse_mb
import neo_udp as N

def real_frames(path):
    """Devuelve lista de (dir, m) de cada frame DUML interno (des-envuelto)."""
    out = []
    for ts, d, seq, fr in walk_frames(path):
        m = unwrap(fr)
        if m:
            out.append((d, m))
    return out

def check(name, rebuilt, raw):
    ok = rebuilt == raw
    if ok:
        print(f"  [OK ] {name}: {len(raw)}B identico")
    else:
        diff = next((i for i,(a,b) in enumerate(zip(rebuilt,raw)) if a!=b), None)
        print(f"  [DIFF] {name}: len build={len(rebuilt)} real={len(raw)} "
              f"1er byte distinto @0x{diff:02x}" if diff is not None
              else f"  [DIFF] {name}: longitudes {len(rebuilt)} vs {len(raw)}")
        print(f"         build={rebuilt.hex()}")
        print(f"         real ={raw.hex()}")
    return ok

def validate(path):
    print("="*74); print("VALIDACION DE BUILDERS vs", path)
    frames = real_frames(path)
    up = [m for d,m in frames if d == "UP"]
    total = ok = 0

    # 1) Reconstruccion generica: TODO frame UP MB via mb_frame() debe ser identico.
    print("\n-- 1) reconstruccion generica MB (CRC-8 cab + CRC-16) sobre UP --")
    gen_ok = gen_n = 0
    fails = collections.Counter()
    for m in up:
        raw = m["raw"]
        rebuilt = N.mb_frame(m["snd"], m["rcv"], m["dseq"], m["attr"],
                             m["cset"], m["cid"], m["payload"])
        gen_n += 1
        if rebuilt == raw: gen_ok += 1
        else: fails[(m["cset"], m["cid"])] += 1
    print(f"  {gen_ok}/{gen_n} frames UP reconstruidos identicos")
    if fails:
        print("  fallos por (cset,cid):", {f"0x{c:02x}/0x{i:02x}": n for (c,i),n in fails.items()})
    total += 1; ok += (gen_ok == gen_n)

    # helper: primer UP con (cset,cid)[y filtro opcional]
    def first(cset, cid, pred=None):
        for m in up:
            if m["cset"]==cset and m["cid"]==cid and (pred is None or pred(m)):
                return m
        return None

    print("\n-- 2) builders semanticos --")
    # modo 0x03/0xf9 (el SET-modo real lleva prefijo 878867a3; hay otros 0xf9 distintos)
    m = first(0x03, 0xf9, lambda m: m["payload"][:4]==bytes.fromhex("878867a3"))
    if m:
        mode = m["payload"][4]
        total += 1; ok += check(f"mode_frame(0x{mode:02x})", N.mode_frame(m["dseq"], mode), m["raw"])

    # autoridad var-02
    m = first(0x03, 0x20, lambda m: m["payload"] and m["payload"][0]==0x02)
    if m:
        ts = struct.unpack("<I", m["payload"][9:13])[0]
        total += 1; ok += check("authority var-02", N.authority_frame(m["dseq"], ts, 0x02), m["raw"])
    # autoridad var-03 (GPS extraido pero NO impreso)
    m = first(0x03, 0x20, lambda m: m["payload"] and m["payload"][0]==0x03)
    if m:
        lat, lon = struct.unpack("<ii", m["payload"][1:9])
        ts = struct.unpack("<I", m["payload"][9:13])[0]
        total += 1; ok += check("authority var-03 (GPS oculto)",
                                N.authority_frame(m["dseq"], ts, 0x03, lat, lon), m["raw"])

    # heartbeat 0x03/0xd7: init y uno con contador
    m = first(0x03, 0xd7, lambda m: m["payload"]==bytes.fromhex("01010000"))
    if m:
        total += 1; ok += check("d7_frame init", N.d7_frame(m["dseq"], 0, init=True), m["raw"])
    m = first(0x03, 0xd7, lambda m: len(m["payload"])==8 and m["payload"][:4]==bytes.fromhex("01040000"))
    if m:
        ctr = struct.unpack("<I", m["payload"][4:8])[0]
        total += 1; ok += check(f"d7_frame(ctr={ctr})", N.d7_frame(m["dseq"], ctr), m["raw"])

    # lote 0x03/0xf8 primer batch
    m = first(0x03, 0xf8, lambda m: m["payload"]==N.F8_FIRST_BATCH)
    if m:
        total += 1; ok += check("f8_frame(1er batch)", N.f8_frame(m["dseq"]), m["raw"])

    # despegue 0x03/0xda 05ffffffff
    m = first(0x03, 0xda, lambda m: m["payload"]==bytes.fromhex("05ffffffff"))
    if m:
        total += 1; ok += check("takeoff_frame", N.takeoff_frame(m["dseq"]), m["raw"])

    # rafaga 0x03/0x34, 0x03/0x3c, 0x0d/0x03
    m = first(0x03, 0x34, lambda m: len(m["payload"])==0)
    if m: total += 1; ok += check("arm34_frame", N.arm34_frame(m["dseq"]), m["raw"])
    m = first(0x03, 0x3c, lambda m: len(m["payload"])==0)
    if m: total += 1; ok += check("arm3c_frame", N.arm3c_frame(m["dseq"]), m["raw"])
    m = first(0x0d, 0x03, lambda m: m["payload"]==bytes.fromhex("00000000"))
    if m: total += 1; ok += check("arm0d03_frame", N.arm0d03_frame(m["dseq"]), m["raw"])

    print(f"\nRESULTADO {os.path.basename(path)}: {ok}/{total} comprobaciones OK")
    return ok == total

if __name__ == "__main__":
    paths = sys.argv[1:] or ["../../../Quinta prueba.pcap", "../../../Octava prueba.pcap"]
    allok = all(validate(p) for p in paths)
    print("\n" + ("TODO VALIDADO OK" if allok else "HAY DIFERENCIAS -- REVISAR"))
    sys.exit(0 if allok else 1)
