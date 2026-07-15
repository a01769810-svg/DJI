#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mapflight.py — Vuela un patron SUAVE y GRABA video a la vez (para mapeo SLAM). EXP-032.

Combina el arranque/sosten/captura de video (video.py) con el control de vuelo. Usa DOS
HILOS: el RECEPTOR drena el socket continuamente (para no perder video, ni siquiera cuando
el hilo de control esta ocupado); el hilo de CONTROL manda todo el uplink (replay del init
de la app que arranca el video + AUTO_FLY + sticks + ACK type-0x04) por type-5 CRUDO
respetando la ventana RX del dron (no usa send_command, cuyo _pump descarta video).

MODOS:
  (sin flags)         DRY: arranca y GRABA video en TIERRA, sticks NEUTRO, SIN despegar.
                      Valida la maquina combinada de forma SEGURA.
  --fly --armed-ok    VUELO REAL: tras estabilizar el video, despega, hace un patron
                      simetrico suave (paralaje para SLAM) y aterriza. Tecleas VOLAR.

SEGURIDAD: patron simetrico (vuelve ~al inicio), deflexion baja, tope de tiempo (--cap),
Ctrl+C = ATERRIZA (throttle-min). El video se graba y decodifica igual que video.py.

USO (via neo.ps1):
  .\\neo.ps1 mapflight.py                              # DRY: graba en tierra (seguro)
  .\\neo.ps1 mapflight.py --fly --armed-ok             # VUELO+GRABACION (patron por defecto)
  .\\neo.ps1 mapflight.py --fly --armed-ok --cap 30    # limitar vuelo a 30s (recomendado 1a vez)
Luego decodificar:  .\\.venv\\Scripts\\python mapflight.py --decode map_video.h265
"""
import argparse, socket, sys, threading, time
import neo_udp as N
import flight as F
import video as V

PCAP_DEFAULT = "C:\\Users\\santi\\Desktop\\DJI project\\Novena captura.pcap"

# --- Patron de vuelo (suave, simetrico, da PARALAJE para SLAM). Deflexion BAJA (interior). ---
DEF = 130
def _mv(dr=0, dp=0, dyaw=0):
    return (1024 + dr, 1024 + dp, 1024, 1024 + dyaw)
NEUTRAL = F.NEUTRAL
FWD, BACK  = _mv(dp=DEF),  _mv(dp=-DEF)
LEFT, RIGHT = _mv(dr=-DEF), _mv(dr=DEF)
YAWR, YAWL = _mv(dyaw=DEF), _mv(dyaw=-DEF)

# secuencia (sticks, segundos). Simetrica: cada movimiento y su opuesto -> vuelve ~al inicio.
PATTERN = [
    (NEUTRAL, 5.0),                                   # estabilizar
    (FWD, 2.0), (NEUTRAL, 1.5), (BACK, 2.0), (NEUTRAL, 1.5),
    (LEFT, 2.0), (NEUTRAL, 1.5), (RIGHT, 2.0), (NEUTRAL, 1.5),
    (YAWR, 3.0), (NEUTRAL, 1.5), (YAWL, 3.0), (NEUTRAL, 1.5),
]

def stick_at(t_air, cap):
    """Devuelve los sticks para 't_air' segundos en el aire, recorriendo PATTERN en bucle
    hasta 'cap'; al pasar cap, NEUTRO (el aterrizaje lo maneja el estado LAND)."""
    if t_air >= cap:
        return NEUTRAL
    total = sum(d for _, d in PATTERN)
    tt = t_air % total
    acc = 0.0
    for sticks, d in PATTERN:
        if tt < acc + d:
            return sticks
        acc += d
    return NEUTRAL


def _receiver(s, st):
    """Hilo que SOLO recibe: captura video (con subheader) y mantiene la ventana RX del dron."""
    while not st["stop"]:
        try:
            s.sock.settimeout(0.2)
            d, a = s.sock.recvfrom(65535)
        except (socket.timeout, BlockingIOError, OSError):
            continue
        if a[0] != N.DRONE[0] or len(d) < 8:
            continue
        seq = d[4] | (d[5] << 8)
        if d[6] == 0x02:
            if len(d) > 8 + V.SUBHDR:
                if st["vlast"] is not None and seq < st["vlast"] - 32768:
                    st["vwrap"] += 1
                st["vlast"] = seq
                st["vpkts"].append((seq + st["vwrap"] * 65536, d[8:]))
            st["max_vid"] = seq
        elif d[6] == 0x01:
            st["max_tel"] = seq
            w = N.drone_type5_recv_window(d)
            if w:
                if w[0] > s.send_start:
                    s.send_start = w[0]
                s.drone_next = w[1]
        o = N.find_osd_general(d)                      # estado del FC (para saber si arma)
        if o:
            st["osd"] = o


def raw_send(s, mb):
    """Envia un frame MB como type-5 CRUDO (sin el _pump que descarta video)."""
    pkt = N.build_type5(s.session, s.seq, s.send_start, s.seq, s.ctr, mb)
    s.sock.sendto(pkt, N.DRONE)
    s.seq = (s.seq + 8) & 0xffff
    s.ctr = (s.ctr + 1) & 0xff


def _events_no_sticks(pcap, tmax):
    """Comandos uplink de la app (para arrancar+mantener video) EXCLUYENDO los sticks
    0x01/0x0a de la app (usamos NUESTROS sticks para volar)."""
    out = []
    for rel, mb in V._app_uplink_mb(pcap, tmax):
        is_stick = any(cs == 0x01 and ci == 0x0a for _, cs, ci, _ in N.scan_duml(mb))
        if not is_stick:
            out.append((rel, mb))
    return out


def run(args):
    real = args.fly and args.armed_ok
    print("=" * 64)
    print("  mapflight.py  —  %s" % ("VUELO + GRABACION" if real else "DRY (graba en tierra, sin despegar)"))
    print("=" * 64)
    if args.fly and not args.armed_ok:
        print("!! --fly requiere --armed-ok. Abortado."); return

    # Los flags --fly --armed-ok YA son la confirmacion (sin tecleo). Aviso y arranca:
    # hay ~tvideo s en tierra antes del despegue y Ctrl+C aborta/aterriza en cualquier momento.
    if real:
        print("\n" + "!" * 64)
        print(" VUELO REAL + GRABACION. Area despejada + supervisado.")
        print(" Despega en ~%ds (tras estabilizar el video). Cap de vuelo: %ds. Ctrl+C = ATERRIZAR." % (args.tvideo, args.cap))
        print("!" * 64, flush=True)

    s = N.Type5Session()
    if not s.open():
        print("SIN ack -> revisa WiFi del Neo / DJI Fly cerrado."); return
    try:
        s.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 16 * 1024 * 1024)
    except Exception:
        pass
    events = _events_no_sticks(args.pcap, args.tmax)
    print("hello -> ACK. comandos de arranque de video (sin sticks): %d  -> arrancando ya" % len(events), flush=True)

    st = {"vpkts": [], "vwrap": 0, "vlast": None, "max_vid": 0, "max_tel": 0, "osd": None, "stop": False}
    rx = threading.Thread(target=_receiver, args=(s, st), daemon=True)
    rx.start()

    t0 = time.time()
    ei = 0
    last_ack = last_stick = last_report = last_mode = last_auth = -1.0
    wctr = 0xA000; mdseq = 0xd000; adseq = 0xc000
    takeoff_sent = False
    landing = False
    land_start = None
    t_takeoff = args.tvideo
    # fin: DRY corre 'tmax' s; FLY corre hasta takeoff+cap+aterrizaje
    end_dry = min(args.tmax, 40.0)
    try:
        while True:
            t = time.time() - t0
            # 1) replay del init de la app (arranca el video), respetando la ventana. En VUELO
            #    se DETIENE 1s antes del despegue: asi la ventana type-5 queda LIMPIA para que
            #    el AUTO_FLY y los sticks pasen (el video ya se sostiene con el ACK type-0x04).
            if (not real) or t < t_takeoff - 6.0:      # SETTLE limpio de 6s antes del despegue
                while ei < len(events) and events[ei][0] <= t:
                    if ((s.seq - s.drone_next) & 0xffff) > s.WINDOW:
                        break
                    try:
                        raw_send(s, events[ei][1])
                    except Exception:
                        pass
                    ei += 1
            # 2) ACK type-0x04 ~30Hz (sostiene el video)
            if t - last_ack >= 0.033:
                try:
                    s.sock.sendto(V._ack4(s.session, st["max_tel"], st["max_vid"]), N.DRONE)
                except Exception:
                    pass
                last_ack = t
            # 3) maquina de estados de vuelo -> sticks actuales
            if not real:
                sticks = NEUTRAL
                if t > end_dry:
                    break
            else:
                if not takeoff_sent and t >= t_takeoff:
                    o = st["osd"]
                    if o:
                        why = N.START_FAIL_ENUM.get(o["start_fail_reason"], "0x%02x?" % o["start_fail_reason"])
                        print(">>> OSD pre-despegue: estado=%s motores=%s en_tierra=%s | MOTIVO NO-ARRANQUE: %s"
                              % (N.FLYC_STATE_ENUM.get(o["flyc_state"], "?"), o["motor_on"], o["on_ground"], why), flush=True)
                    else:
                        print(">>> OSD pre-despegue: NO recibido (FC no nos empuja OSD = no enganchado)", flush=True)
                    print(">>> AUTO_FLY (despegue) en t+%.1f" % t, flush=True)
                    raw_send(s, N.wrap_5101(wctr, N.funcctrl_frame(mdseq, N.AUTO_FLY)))
                    wctr = (wctr + 1) & 0xffffffff; mdseq = (mdseq + 1) & 0xffff
                    takeoff_sent = True
                if takeoff_sent:
                    t_air = t - t_takeoff
                    if not landing and (t_air >= args.cap):
                        landing = True; land_start = t
                        print(">>> CAP alcanzado -> ATERRIZANDO (throttle-min)", flush=True)
                    if landing:
                        sticks = F.THROTTLE_MIN
                        if st["max_vid"] and (t - land_start) > 14.0:
                            break
                    else:
                        sticks = stick_at(t_air, args.cap)
                else:
                    sticks = NEUTRAL
            # 4) NUESTROS sticks (bare, 20Hz). Modo/autoridad/sub13 vienen del replay; en
            #    vuelo real reforzamos modo (wrapped, 10Hz) + autoridad (bare, 1Hz) como flight.py.
            if t - last_stick >= 0.05:
                _send_stick(s, sticks); last_stick = t
            if real:                                   # modo+autoridad DESDE EL SUELO (settle
                #                                        continuo; el FC lo necesita para armar)
                if t - last_mode >= 0.1:
                    try:
                        raw_send(s, N.wrap_5101(wctr, N.mode_frame(mdseq)))
                    except Exception:
                        pass
                    wctr = (wctr + 1) & 0xffffffff; mdseq = (mdseq + 1) & 0xffff; last_mode = t
                if t - last_auth >= 1.0:
                    try:
                        raw_send(s, N.authority_frame(adseq, int(time.time()), 0x02))
                    except Exception:
                        pass
                    adseq = (adseq + 1) & 0xffff; last_auth = t
            # 5) reporte
            if t - last_report >= 1.0:
                phase = "DRY" if not real else ("LAND" if landing else ("AIR" if takeoff_sent else "GROUND"))
                mot = st["osd"]["motor_on"] if st["osd"] else "?"
                print("  t+%5.1f [%s] video=%d pkts, vseq=0x%04x, motores=%s" % (t, phase, len(st["vpkts"]), st["max_vid"], mot), flush=True)
                last_report = t
    except KeyboardInterrupt:
        print("\n!! Ctrl+C -> ATERRIZANDO (throttle-min)", flush=True)
        if real and takeoff_sent:
            t1 = time.time()
            while time.time() - t1 < 12.0:
                _send_stick(s, F.THROTTLE_MIN)
                try:
                    s.sock.sendto(V._ack4(s.session, st["max_tel"], st["max_vid"]), N.DRONE)
                except Exception:
                    pass
                time.sleep(0.05)
    finally:
        st["stop"] = True
        time.sleep(0.3)
        s.sock.close()

    # guardar video (frames completos, recortado al primer keyframe)
    es, kept, dropped = V._reassemble_frames(list(st["vpkts"]))
    k = es.find(b"\x00\x00\x00\x01\x40")
    if k > 0:
        es = es[k:]
    with open(args.out, "wb") as fp:
        fp.write(es)
    print("\n>>> VIDEO: %d paquetes; frames completos=%d, descartados=%d; %.2f MB -> %s"
          % (len(st["vpkts"]), kept, dropped, len(es) / 1e6, args.out))
    print(">>> Decodifica:  .\\.venv\\Scripts\\python tools\\neo_control\\mapflight.py --decode %s" % args.out)


def _send_stick(s, sticks):
    """Manda el frame de stick (mismo formato EXP-026 que flight.py) por type-5 crudo."""
    r, p, th, y = sticks
    ctr = int(time.time() * 1000) & 0xffff
    val = (((r & 0x7ff) | ((p & 0x7ff) << 11) | ((th & 0x7ff) << 22) | ((y & 0x7ff) << 33))
           ).to_bytes(6, "little")
    dseq = getattr(_send_stick, "_dseq", 0xe600)
    mb = N.mb_frame(0x02, 0xa9, dseq, 0x00, 0x01, 0x0a,
                    b"\x01\x0d\x00" + val + b"\x40\x00\x02\x00\x00\x06\x55\x01\x04\x56\x08"
                    + ctr.to_bytes(2, "little") + b"\x00\x00\x00\x00\x00\x00")
    _send_stick._dseq = (dseq + 1) & 0xffff
    raw_send(s, mb)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fly", action="store_true", help="VUELO REAL (despega y hace el patron)")
    ap.add_argument("--armed-ok", dest="armed_ok", action="store_true", help="2do candado de seguridad")
    ap.add_argument("--pcap", default=PCAP_DEFAULT, help="captura para el arranque de video")
    ap.add_argument("--tmax", type=float, default=50.0, help="replay del init hasta t+N (mantiene keyframes)")
    ap.add_argument("--tvideo", type=float, default=18.0, help="segundos en tierra antes de despegar (replay ~12s + settle limpio ~6s)")
    ap.add_argument("--cap", type=float, default=30.0, help="segundos MAXIMOS en el aire antes de aterrizar")
    ap.add_argument("--out", default="map_video.h265", help="archivo de video de salida")
    ap.add_argument("--decode", metavar="FILE", default=None, help="decodificar un .h265 (usa el .venv)")
    args = ap.parse_args()
    if args.decode:
        V.decode(args.decode)
    else:
        run(args)


if __name__ == "__main__":
    main()
