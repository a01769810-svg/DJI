#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
video.py — Recibe el VIDEO EN VIVO del DJI Neo desde la sesion propia (EXP-030).
SEGURO EN SUELO: NO despega, NO arma (solo engancha la sesion y escucha). La camara
transmite tambien en tierra, asi que se prueba sin volar.

El video viaja en el canal 9003 como paquetes DJI type-0x02: cabecera 8B + sub-encabezado
de fragmento 12B + trozo del elementary stream HEVC. Reensamblando body[12:] en orden se
reconstruye el .h265 (ver analysis/video_reassemble.py, validado offline).

DOS MODOS (por que OpenCV vive en el .venv y neo.ps1 usa el python del sistema):
  1) CAPTURA (solo sockets, sin cv2)  -> via neo.ps1 (necesita WiFi del Neo):
       .\\neo.ps1 video.py --secs 12               # captura 12s -> neo_video.h265
  2) DECODIFICAR (usa cv2) -> con el python del .venv (sin WiFi):
       .\\.venv\\Scripts\\python tools\\neo_control\\video.py --decode neo_video.h265
       (guarda frames en ./frames/ y reporta resolucion y nº de frames)
"""
import argparse, os, socket, time
import neo_udp as N

SUBHDR = 12   # sub-encabezado de fragmento antes del payload del codec


def capture(secs, out):
    """Engancha la sesion y captura los paquetes de video (0x02) a un .h265. Sin cv2."""
    import flight as F
    s = N.Type5Session()
    print("=" * 64)
    print("  video.py  —  CAPTURA de video en vivo (sin volar, SEGURO en suelo)")
    print("  seed=0x%04x session=0x%04x  captura=%.0fs -> %s" % (s.seed, s.session, secs, out))
    print("=" * 64)
    if not s.open():
        print("SIN ack -> revisa WiFi del Neo / DJI Fly cerrado."); return
    print("hello -> ACK. Sesion abierta.")
    f = F.Flight(s)
    for fr in F.INIT:
        s.send_command(fr); time.sleep(0.03)
    ok = f.engage()
    print(">>> ENGANCHE 0x51: %s" % ("OK" if ok else "FALLO (no llego el serial)"), flush=True)

    es = bytearray()
    vid_pkts = other = 0
    t0 = last_sub = last_ka = last_report = time.time()
    print("--- capturando video (0x02)... ---", flush=True)
    while time.time() - t0 < secs:
        now = time.time()
        if f.serial and now - last_sub >= 0.2:
            f.sub13(); last_sub = now                    # mantiene la sesion/stream vivos
        if now - last_ka >= 0.5:
            s.keepalive(); last_ka = now
        s.sock.settimeout(0.05)
        try:
            d, a = s.sock.recvfrom(65535)
        except (socket.timeout, BlockingIOError):
            d = None
        if d and a[0] == N.DRONE[0]:
            if len(d) >= 8 and d[6] == 0x02:             # paquete de video
                body = d[8:]
                if len(body) > SUBHDR:
                    es += body[SUBHDR:]
                    vid_pkts += 1
            else:
                other += 1
        if now - last_report >= 1.0:
            print("  t+%4.1f  video_pkts=%d  ES=%.1f MB  (otros=%d)"
                  % (now - t0, vid_pkts, len(es) / 1e6, other), flush=True)
            last_report = now
    s.sock.close()
    with open(out, "wb") as fp:
        fp.write(es)
    print("\nescrito %s : %d paquetes de video, %.1f MB" % (out, vid_pkts, len(es) / 1e6))
    if vid_pkts == 0:
        print(">>> NO llego video. Puede que el stream necesite un comando de arranque de")
        print("    camara; siguiente paso seria investigarlo. (otros paquetes=%d)" % other)
    else:
        print(">>> OK. Decodifica con:")
        print("    .\\.venv\\Scripts\\python tools\\neo_control\\video.py --decode %s" % out)


def decode(path, save_dir="frames", every=15, max_frames=None):
    """Decodifica el .h265 con OpenCV (del .venv), reporta resolucion/frames y guarda
    algunos frames en save_dir. Requiere cv2."""
    try:
        import cv2
    except ImportError:
        print("cv2 no disponible en este python. Usa el del .venv:")
        print("  .\\.venv\\Scripts\\python tools\\neo_control\\video.py --decode %s" % path)
        return
    print("OpenCV", cv2.__version__, "decodificando", path)
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        print("no se pudo abrir el stream."); return
    if save_dir and not os.path.isdir(save_dir):
        os.makedirs(save_dir)
    n = saved = 0; first = None
    while True:
        r, frame = cap.read()
        if not r:
            break
        if first is None:
            first = frame.shape
        if save_dir and n % every == 0:
            cv2.imwrite(os.path.join(save_dir, "frame_%05d.png" % n), frame); saved += 1
        n += 1
        if max_frames and n >= max_frames:
            break
    cap.release()
    print("frames decodificados: %d   resolucion: %s   guardados: %d en %s/"
          % (n, first, saved, save_dir))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--secs", type=float, default=12.0, help="segundos a capturar (modo captura)")
    ap.add_argument("--out", default="neo_video.h265", help="archivo .h265 de salida (captura)")
    ap.add_argument("--decode", metavar="FILE", default=None,
                    help="decodificar un .h265 con OpenCV (usa el python del .venv)")
    ap.add_argument("--every", type=int, default=15, help="guardar 1 de cada N frames al decodificar")
    args = ap.parse_args()

    if args.decode:
        decode(args.decode, every=args.every)
    else:
        capture(args.secs, args.out)


if __name__ == "__main__":
    main()
