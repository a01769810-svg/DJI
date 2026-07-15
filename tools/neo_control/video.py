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
import argparse, collections, os, socket, struct, time
import neo_udp as N

SUBHDR = 12   # sub-encabezado de fragmento antes del payload del codec


def _reassemble_frames(pkts, sub=SUBHDR):
    """Reensambla emitiendo SOLO frames COMPLETOS. Un frame (agrupado por frame_num=body[8])
    esta completo si sus 'partes' (body[10:12]) son contiguas, cada parte no-terminal aparece
    >=2 veces (sus 2 paquetes MTU) y termina en un paquete corto (<1452). Los frames con
    partes perdidas se DESCARTAN para no corromper el decoder. Devuelve (bytes, kept, dropped).
    Validado offline: 1779 frames ok / 1 descartado -> decodifica 1769 a 1080p."""
    pkts.sort(key=lambda x: x[0])
    out = bytearray(); kept = dropped = 0; i = 0; n = len(pkts)
    while i < n:
        fn = pkts[i][1][8]; j = i; frame = []
        while j < n and pkts[j][1][8] == fn:
            frame.append(pkts[j][1]); j += 1
        pc = collections.Counter((b[10] | (b[11] << 8)) for b in frame)
        pmin, pmax = min(pc), max(pc)
        contiguous = (pmax - pmin + 1) == len(pc)
        nonterm_ok = all(pc[p] >= 2 for p in range(pmin, pmax))
        term_short = any((len(b) - sub) < 1452 for b in frame if (b[10] | (b[11] << 8)) == pmax)
        if contiguous and nonterm_ok and term_short:
            for b in frame:
                out += b[sub:]
            kept += 1
        else:
            dropped += 1
        i = j
    return bytes(out), kept, dropped


def _iter_pcap(path):
    """Lector minimo de pcap clasico linktype 101 (RAW IP), LE. Devuelve (ts, ip_bytes)."""
    with open(path, "rb") as f:
        gh = f.read(24)
        if gh[:4] != b"\xd4\xc3\xb2\xa1":
            raise SystemExit("pcap magic inesperado: %s" % gh[:4].hex())
        while True:
            rh = f.read(16)
            if len(rh) < 16:
                break
            ts_s, ts_us, incl, orig = struct.unpack("<IIII", rh)
            data = f.read(incl)
            if len(data) < incl:
                break
            yield ts_s + ts_us / 1e6, data


def _app_uplink_mb(path, tmax):
    """Extrae, en orden, (rel_t, mb_bytes) de cada paquete type-5 UPLINK (app->dron) del
    pcap hasta tmax segundos: mb = region DUML tras la cabecera+flowcontrol (offset 0x14)."""
    DRONE_IP = b"\xc0\xa8\x02\x01"          # 192.168.2.1
    out = []
    t0 = None
    for ts, ip in _iter_pcap(path):
        if len(ip) < 20 or (ip[0] >> 4) != 4 or ip[9] != 17:   # IPv4 + UDP
            continue
        ihl = (ip[0] & 0x0f) * 4
        udp = ip[ihl:]
        if len(udp) < 8:
            continue
        sp, dp = struct.unpack("!HH", udp[:4])
        if 9003 not in (sp, dp):
            continue
        dst = ip[16:20]
        if dst != DRONE_IP:                 # solo uplink (hacia el dron)
            continue
        pl = udp[8:]
        if len(pl) < 0x15 or pl[6] != 0x05:  # type-5 (comandos)
            continue
        if t0 is None:
            t0 = ts
        rel = ts - t0
        if rel > tmax:
            break
        out.append((rel, pl[0x14:]))
    return out


def capture(secs, out, start=False):
    """Engancha la sesion y captura los paquetes de video (0x02) a un .h265. Sin cv2.
    start=True: ademas streamea los comandos de camara (0x02/*) que la app usa para
    ARRANCAR el stream de video (EXP-030), para probar si empieza a llegar video."""
    import flight as F
    s = N.Type5Session()
    print("=" * 64)
    print("  video.py  —  CAPTURA de video en vivo (sin volar, SEGURO en suelo)")
    print("  seed=0x%04x session=0x%04x  captura=%.0fs -> %s%s"
          % (s.seed, s.session, secs, out, "  [+arranque camara]" if start else ""))
    print("=" * 64)
    if not s.open():
        print("SIN ack -> revisa WiFi del Neo / DJI Fly cerrado."); return
    print("hello -> ACK. Sesion abierta.")
    f = F.Flight(s)
    for fr in F.INIT:
        s.send_command(fr); time.sleep(0.03)
    ok = f.engage()
    print(">>> ENGANCHE 0x51: %s" % ("OK" if ok else "FALLO (no llego el serial)"), flush=True)
    if start:
        f._wrapped(N.CAM_B5)                             # one-shot de arranque
        print(">>> comandos de camara de arranque activados (0xb5 + streams 0xd8/0xe8/0xeb)", flush=True)

    es = bytearray()
    vid_pkts = other = 0
    t0 = last_sub = last_ka = last_report = last_cam = time.time()
    print("--- capturando video (0x02)... ---", flush=True)
    while time.time() - t0 < secs:
        now = time.time()
        if start and now - last_cam >= 0.3:              # ~3Hz los streams de camara
            f._wrapped(N.CAM_D8); f._wrapped(N.CAM_E8); f._wrapped(N.CAM_EB); last_cam = now
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


def _ack4(session, tel, vid):
    """Construye el paquete ACK type-0x04 que la app manda a ~50Hz para sostener el video.
    Formato observado (34B): cabecera(8) + 3 ventanas [start(2) end(2) 0000(4)] + 0000.
    Ventanas 1 y 2 rastrean la seq de VIDEO; la 3 la de telemetria (segun la captura)."""
    def win(a, b):
        return struct.pack("<HH", a & 0xffff, b & 0xffff) + b"\x00\x00\x00\x00"
    body = win(vid, vid) + win(vid, vid) + win(tel, tel) + b"\x00\x00"
    length = 8 + len(body)                       # 34
    h = bytearray(8)
    h[0] = length & 0xff
    h[1] = 0x80 | ((length >> 8) & 0x7f)
    h[2] = session & 0xff
    h[3] = (session >> 8) & 0xff
    h[6] = 0x04
    x = 0
    for b in h[:7]:
        x ^= b
    h[7] = x
    return bytes(h) + body


def replay(pcap, tmax=13.0, watch=15.0, out="neo_video.h265"):
    """EXP-031: REPLAY del init completo de la app. Extrae del pcap todos los comandos
    uplink que la app manda antes de que arranque el video (hasta tmax s), y los reproduce
    VERBATIM en nuestra sesion (respetando el ritmo original), mientras captura el video
    (0x02). Si el video arranca -> el init completo era la pieza que faltaba. Sin volar."""
    s = N.Type5Session()
    print("=" * 64)
    print("  video.py --replay  —  reproduce el init de la app para arrancar el video")
    print("  pcap=%s  init hasta t+%.0fs  escucha +%.0fs" % (os.path.basename(pcap), tmax, watch))
    print("=" * 64)
    events = _app_uplink_mb(pcap, tmax)
    print("comandos uplink de la app a reproducir: %d" % len(events))
    if not s.open():
        print("SIN ack -> revisa WiFi del Neo / DJI Fly cerrado."); return
    # buffer de recepcion GRANDE: un keyframe llega en una rafaga de ~100 paquetes de golpe;
    # con buffer chico se desborda y perdemos justo el keyframe (solo quedan P-frames).
    try:
        s.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 16 * 1024 * 1024)
    except Exception:
        pass
    print("hello -> ACK. Reproduciendo init + ACK type-0x04 continuo para sostener el video...")

    vpkts = []                       # (useq, full_body) para reensamblar por frames completos
    vwrap = 0; vlast = None          # des-envoltura del seq de 16 bits (wrap cada 65536)
    vid_pkts = 0; vbytes = 0
    max_vid = max_tel = 0
    ei = 0
    t_start = time.time()
    last_ack = last_ka = last_iframe = -1.0
    wctr = 0x9000                                # contador del envoltorio 0x51/01 (alto, sin choque)
    dctr = 0xf000
    end = events[-1][0] + watch if events else watch
    report = 1.0
    while True:
        now = time.time() - t_start
        if now > end:
            break
        # 1) reproducir los comandos de init de la app a su ritmo original. OJO: NO usar
        #    s.send_command() aqui -> su control de flujo llama a _pump() que drena el
        #    socket y DESCARTA los paquetes de video (perdiamos la rafaga del keyframe).
        #    Enviamos el type-5 crudo, sin pump; el drenado de video lo hace el paso 3.
        while ei < len(events) and events[ei][0] <= now:
            # NO rebasar la ventana RX del dron: si nos adelantamos, esperar (break) a que
            # el paso 3 drene video y avance drone_next. Asi el dron ACEPTA y procesa los
            # comandos que disparan el keyframe, sin el pump de send_command que descarta video.
            if ((s.seq - s.drone_next) & 0xffff) > s.WINDOW:
                break
            try:
                mb = events[ei][1]
                pkt = N.build_type5(s.session, s.seq, s.send_start, s.seq, s.ctr, mb)
                s.sock.sendto(pkt, N.DRONE)
                s.seq = (s.seq + 8) & 0xffff
                s.ctr = (s.ctr + 1) & 0xff
            except Exception:
                pass
            ei += 1
        # 2) ACK type-0x04 CONTINUO (~50Hz) desde el principio: cuando el video onsete
        #    durante el replay, ya lo estamos reconociendo y el dron no lo corta.
        if now - last_ack >= 0.033:               # ~30Hz (menos uplink -> menos congestion)
            try:
                # ACK simple con el max recibido (el seq del video NO es contiguo, asi que
                # una "frontera" por +8 se atasca y confunde al dron).
                s.sock.sendto(_ack4(s.session, max_tel, max_vid), N.DRONE)
            except Exception:
                pass
            last_ack = now
        if now - last_ka >= 0.5:
            s.keepalive(); last_ka = now
        # (El Request IFrame 0x02/0xb3 CORTA el stream en el Neo -> deshabilitado. Para
        #  el keyframe dependemos de los IDR naturales del encoder: capturar mas tiempo.)
        # 3) drenar TODO el downlink disponible por vuelta (hasta 256 paquetes): asi no se
        #    pierden las rafagas de keyframe. Capturar video, rastrear seq para el ACK.
        s.sock.settimeout(0.004)
        for _ in range(256):
            try:
                d, a = s.sock.recvfrom(65535)
            except (socket.timeout, BlockingIOError):
                break
            if a[0] != N.DRONE[0] or len(d) < 8:
                continue
            seq = d[4] | (d[5] << 8)
            if d[6] == 0x02:
                if len(d) > 8 + SUBHDR:
                    if vlast is not None and seq < vlast - 32768:   # wrap del seq de 16 bits
                        vwrap += 1
                    vlast = seq
                    vpkts.append((seq + vwrap * 65536, d[8:]))       # body COMPLETO (subheader incl.)
                    vid_pkts += 1; vbytes += len(d) - 8 - SUBHDR
                max_vid = seq
            elif d[6] == 0x01:
                max_tel = seq
                # mantener COHERENTE la ventana de envio type-5 (send_start/drone_next) desde
                # la telemetria, para que el envio crudo del replay sea aceptado por el dron
                # (sin esto el dron rechaza los comandos que disparan el keyframe).
                w = N.drone_type5_recv_window(d)
                if w:
                    if w[0] > s.send_start:
                        s.send_start = w[0]
                    s.drone_next = w[1]
        if now >= report:
            print("  t+%4.1f  video=%d pkts (%.2f MB)  vseq=0x%04x" % (now, vid_pkts, vbytes/1e6, max_vid), flush=True)
            report = now + 1.0
    s.sock.close()
    # reensamblar emitiendo SOLO frames completos (descarta los que perdieron partes)
    es, kept, dropped = _reassemble_frames(vpkts)
    # arrancar el stream en el PRIMER KEYFRAME (VPS = 00000001 40): nos colgamos a mitad
    # del stream, que empieza con P-frames indecodificables; el decoder necesita el keyframe.
    k = es.find(b"\x00\x00\x00\x01\x40")
    if k > 0:
        es = es[k:]
    with open(out, "wb") as fp:
        fp.write(es)
    print("\n>>> VIDEO: %d paquetes; frames COMPLETOS=%d, descartados=%d (%.0f%% ok); %.2f MB -> %s"
          % (vid_pkts, kept, dropped, 100.0 * kept / max(1, kept + dropped), len(es) / 1e6, out))
    if kept > 0:
        print(">>> Decodifica con --decode (o lo hago yo).")
    else:
        print(">>> Ningun frame completo -> demasiada perdida; probar 720p o mas cerca.")


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
    ap.add_argument("--start", action="store_true",
                    help="ademas de capturar, manda los comandos de camara que arrancan el "
                         "stream de video (EXP-030). Usar si sin esto llegan 0 paquetes de video")
    ap.add_argument("--replay", metavar="PCAP", default=None,
                    help="EXP-031: reproduce el init completo de la app desde un pcap para "
                         "arrancar el video (ej: '../../Novena captura.pcap')")
    ap.add_argument("--tmax", type=float, default=13.0, help="reproducir init hasta t+N s (replay)")
    ap.add_argument("--watch", type=float, default=40.0,
                    help="segundos de sosten/captura tras el init (replay). Mas tiempo = mas "
                         "chance de atrapar un keyframe natural del encoder (~cada 33s)")
    args = ap.parse_args()

    if args.decode:
        decode(args.decode, every=args.every)
    elif args.replay:
        replay(args.replay, tmax=args.tmax, watch=args.watch, out=args.out)
    else:
        capture(args.secs, args.out, start=args.start)


if __name__ == "__main__":
    main()
