#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
video_reassemble.py — Reensambla el stream de VIDEO del Neo desde un pcap (EXP-030).

El video viaja en el MISMO canal 9003 de la sesion, como paquetes DJI type-0x02 (DN).
Estructura de cada paquete: cabecera DJI de 8 bytes + sub-encabezado de fragmento de
12 bytes + trozo del elementary stream. Concatenando body[12:] en orden se reconstruye
el stream HEVC/H.265 (start-codes 00 00 00 01).

Sub-encabezado (12B): [0:2]=0x7268 seed, [2:4]=seq (eco), [4:8]=0, [8]=nº frame,
[9]=flags, [10:12]=indice de fragmento.

USO:
  python video_reassemble.py "<ruta.pcap>" [salida.h265]
Analiza los NAL reconstruidos y escribe el elementary stream para decodificar aparte.
"""
import sys, os, struct, collections
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import djiudp as J

SUBHDR = 12   # bytes de sub-encabezado de fragmento antes del payload del codec

# Tipos NAL de H.265/HEVC (nal_type = (byte0 >> 1) & 0x3f)
HEVC_NAL = {32: "VPS", 33: "SPS", 34: "PPS", 19: "IDR_W_RADL", 20: "IDR_N_LP",
            21: "CRA", 1: "TRAIL_R", 0: "TRAIL_N", 39: "SEI_PREFIX", 40: "SEI_SUFFIX"}


def extract_video(path):
    """Devuelve los payloads de codec (body[12:]) de cada paquete video 0x02 DN, en orden."""
    chunks = []
    for ts, ip in J.iter_pcap(path):
        r = J.parse_ip_udp(ip)
        if not r:
            continue
        src, dst, sp, dp, pl = r
        if 9003 not in (sp, dp) or dst == J.DRONE_IP:
            continue
        h = J.dji_header(pl)
        if not h or h["ptype"] != 0x02:
            continue
        body = pl[8:]
        if len(body) <= SUBHDR:
            continue
        chunks.append(body[SUBHDR:])
    return chunks


def scan_nals(es):
    """Cuenta NAL units HEVC en el elementary stream (por start-codes 00000001/000001)."""
    counts = collections.Counter()
    i, n = 0, len(es)
    first_types = []
    while i < n - 4:
        if es[i] == 0 and es[i+1] == 0 and es[i+2] == 1:
            nal_type = (es[i+3] >> 1) & 0x3f
            counts[nal_type] += 1
            if len(first_types) < 20:
                first_types.append(nal_type)
            i += 3
        elif es[i] == 0 and es[i+1] == 0 and es[i+2] == 0 and es[i+3] == 1:
            nal_type = (es[i+4] >> 1) & 0x3f
            counts[nal_type] += 1
            if len(first_types) < 20:
                first_types.append(nal_type)
            i += 4
        else:
            i += 1
    return counts, first_types


def main():
    path = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else None
    print("=" * 70)
    print("Reensamblando video de:", path)
    chunks = extract_video(path)
    es = b"".join(chunks)
    print("paquetes video 0x02: %d   bytes de elementary stream: %d (%.1f MB)"
          % (len(chunks), len(es), len(es) / 1e6))
    counts, first = scan_nals(es)
    print("NAL units por tipo (HEVC):")
    for t, c in counts.most_common():
        print("   type %2d %-12s : %d" % (t, HEVC_NAL.get(t, "?"), c))
    print("primeros NAL:", [HEVC_NAL.get(t, str(t)) for t in first])
    vps = counts.get(32, 0); sps = counts.get(33, 0); pps = counts.get(34, 0)
    idr = counts.get(19, 0) + counts.get(20, 0) + counts.get(21, 0)
    slices = idr + counts.get(1, 0) + counts.get(0, 0)
    print("\nDIAGNOSTICO: VPS=%d SPS=%d PPS=%d  IDR/keyframes=%d  frames(aprox slices)=%d"
          % (vps, sps, pps, idr, slices))
    if vps and sps and pps and slices > 5:
        print(">>> Stream HEVC coherente: hay parametros + frames. Reensamblado OK.")
    else:
        print(">>> Stream aun no coherente; revisar tamano de sub-encabezado o reordenado.")
    if out:
        with open(out, "wb") as f:
            f.write(es)
        print("escrito:", out, "(decodificar con ffmpeg/OpenCV para ver frames)")


if __name__ == "__main__":
    main()
