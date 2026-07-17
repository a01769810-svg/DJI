#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mapflight.py — Vuela un patron SUAVE y GRABA video a la vez (para mapeo SLAM). EXP-032.

Combina el arranque/sosten/captura de video (video.py) con el control de vuelo. Usa DOS
HILOS: el RECEPTOR drena el socket continuamente (para no perder video, ni siquiera cuando
el hilo de control esta ocupado); el hilo de CONTROL manda todo el uplink (replay del init
de la app que arranca el video + AUTO_FLY + sticks + ACK type-0x04) por type-5 sin el
_pump de send_command (que descarta video), pero FIABLE: gate a la ventana RX + cache +
RETRANSMISION del seq atascado (raw_send/retransmit). Sin la retransmision, un solo
paquete de uplink perdido atascaba el stream type-5 (ordenado) y el AUTO_FLY nunca armaba
-> ese era el bug del despegue; flight.py no lo tenia porque send_command ya retransmite.

MODOS:
  (sin flags)         DRY: arranca y GRABA video en TIERRA, sticks NEUTRO, SIN despegar.
                      Valida la maquina combinada de forma SEGURA.
  --fly --armed-ok    VUELO REAL de mapeo: estabiliza video -> despega -> SUBE a --alt
                      (throttle, lazo cerrado con la altura) -> patron: traslacion (paralaje)
                      + barrido de yaw en una direccion (cobertura) -> aterriza. La camara se
                      apunta a --cam-pitch (abajo) en lazo cerrado. Los flags son la confirmacion.

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

# --- Patron de vuelo (suave, simetrico, da PARALAJE para SLAM). Deflexion via --defl. ---
# 130 = casi no traslada (interior conservador); ~250 = traslacion visible; ~350 = amplio.
# El paralaje para SLAM NECESITA traslacion real, asi que el default sube a 250. Tope 500.
def _mv(dr=0, dp=0, dyaw=0):
    return (1024 + dr, 1024 + dp, 1024, 1024 + dyaw)
NEUTRAL = F.NEUTRAL

# Pasos de la secuencia de mapeo. Dos tipos:
#   ("move", sticks, secs) -> mantiene 'sticks' 'secs' segundos (traslacion/pausa, LAZO ABIERTO)
#   ("turn", grados)       -> giro de LAZO CERRADO: gira hasta cambiar 'grados' el yaw real del
#                             OSD (grados>0 = DERECHA, ch3+, yaw sube; grados<0 = IZQUIERDA).
YAW_TOL = 8.0          # grados de tolerancia para dar por cerrado un giro
# El Neo gira LENTO (~6 deg/s medido a defl 250). El timeout por giro se escala al angulo
# (respaldo si no cierra): 90deg -> ~19s, 180deg -> ~32s a ~7deg/s + margen.
def _turn_timeout(deg):
    return abs(deg) / 7.0 + 6.0

def build_sequence(defl):
    """Secuencia de MAPEO:
      1) TRASLACION simetrica (FWD/BACK/LEFT/RIGHT) -> PARALAJE (la profundidad para SLAM viene
         de trasladarse). 'el resto esta perfecto' (usuario) -> se conserva igual.
      2) GIROS de lazo cerrado: izquierda 90, derecha 180, izquierda 90 -> cubre pared izq y der
         y regresa al frente. Girar no traslada => seguro; la precision la da el yaw del OSD."""
    d = max(0, min(int(defl), 500))                   # tope de seguridad (rango stick +-660)
    FWD, BACK   = _mv(dp=d),   _mv(dp=-d)
    LEFT, RIGHT = _mv(dr=-d),  _mv(dr=d)
    return [
        ("move", NEUTRAL, 3.0),                        # estabilizar a la altura de mapeo
        # 1) traslacion (paralaje), simetrica -> regresa ~al inicio
        ("move", FWD, 2.0), ("move", NEUTRAL, 1.5), ("move", BACK, 2.0), ("move", NEUTRAL, 1.5),
        ("move", LEFT, 2.0), ("move", NEUTRAL, 1.5), ("move", RIGHT, 2.0), ("move", NEUTRAL, 1.5),
        # 2) giros de cobertura (lazo cerrado): izq 90 -> der 180 -> izq 90
        ("turn", -90), ("move", NEUTRAL, 1.5),
        ("turn", 180), ("move", NEUTRAL, 1.5),
        ("turn", -90), ("move", NEUTRAL, 1.5),
    ]

# Ascenso: el auto-despegue del Neo se queda ~0.7m y su altitude-hold RESISTE empujes
# timidos (+220 no subio nada). Para subir a --alt hay que empujar el throttle FUERTE
# (el stick izquierdo arriba en el RC real; --climb-thr, default +450). El lazo cerrado
# con la altura del OSD lo PARA en --alt. Se construye en run() desde --climb-thr.

class MapSequencer:
    """Ejecuta la secuencia de mapeo paso a paso. Los 'move' son por tiempo (lazo abierto);
    los 'turn' son LAZO CERRADO sobre el yaw del OSD: acumula la rotacion real (des-envolviendo
    el wrap +-180) y gira hasta alcanzar los grados pedidos, frenando cerca del objetivo. Un
    timeout por giro evita quedarse girando si la telemetria falla. done=True al terminar."""
    def __init__(self, sequence, yaw_defl):
        self.seq = sequence
        self.yd_max = max(0, min(int(yaw_defl), 640))   # tope: 1024+640=1664 (< max 1684)
        self.i = 0
        self.step_start = None
        self.yaw_prev = None
        self.accum = 0.0
        self.done = False

    def _advance(self):
        self.i += 1; self.step_start = None; self.yaw_prev = None; self.accum = 0.0

    def sticks(self, t, yaw):
        """Sticks para el paso actual; avanza al terminarlo. NEUTRAL cuando ya acabo todo."""
        if self.i >= len(self.seq):
            self.done = True
            return NEUTRAL
        step = self.seq[self.i]
        if self.step_start is None:                    # primera iteracion del paso
            self.step_start = t; self.yaw_prev = yaw; self.accum = 0.0
        if step[0] == "move":
            _, sticks, secs = step
            if t - self.step_start >= secs:
                self._advance()
            return sticks
        # ("turn", grados): lazo cerrado sobre el yaw
        _, deg = step
        if yaw is not None and self.yaw_prev is not None:
            dy = yaw - self.yaw_prev                    # des-envolver el salto +-180
            if dy > 180: dy -= 360
            elif dy < -180: dy += 360
            self.accum += dy
        if yaw is not None:
            self.yaw_prev = yaw
        remaining = deg - self.accum                    # >0 falta derecha, <0 falta izquierda
        if abs(remaining) <= YAW_TOL or (t - self.step_start) > _turn_timeout(deg):
            self._advance()
            return NEUTRAL
        # deflexion: fuerte casi todo el giro, baja cerca del objetivo pero SIN caer bajo 220
        # (menos que eso el yaw-hold del FC lo frena y no cierra, como paso con el throttle).
        yd = min(self.yd_max, max(220, int(abs(remaining) * 10.0)))
        return (1024, 1024, 1024, 1024 + (yd if remaining > 0 else -yd))  # ch3+ der, ch3- izq


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
        g = N.find_gimbal_position(d)                  # angulo de la camara (para apuntarla)
        if g:
            st["gpitch"] = g["gpitch"]


def raw_send(s, mb):
    """Envia un frame MB como type-5 CRUDO (sin el _pump que descarta video) pero FIABLE:
    respeta la ventana RX del dron y CACHEA el paquete para poder retransmitirlo.
    Devuelve True si se envio, False si la ventana estaba llena (reintentar luego).

    POR QUE (root cause de que mapflight no armara): el canal type-5 es un stream ORDENADO
    y fiable. Si un solo paquete de uplink se pierde (UDP + el video inunda el socket), la
    ventana del dron se ATASCA en ese seq y el FC NO procesa nada posterior -> el AUTO_FLY
    nunca llega procesado. El OSD sigue llegando (downlink) dando falsa señal de 'listo'.
    flight.py (send_command) sobrevive porque pacea a la ventana Y retransmite; el raw_send
    viejo no hacia ninguna de las dos. Esto porta ambas, sin meter recv aqui (el hilo
    receptor mantiene drone_next/send_start)."""
    if ((s.seq - s.drone_next) & 0xffff) > s.WINDOW:   # no adelantarse a lo que el dron acepto
        return False
    pkt = N.build_type5(s.session, s.seq, s.send_start, s.seq, s.ctr, mb)
    s.sent[s.seq] = pkt                                 # cache para retransmision
    s.sock.sendto(pkt, N.DRONE)
    s.seq = (s.seq + 8) & 0xffff
    s.ctr = (s.ctr + 1) & 0xff
    if len(s.sent) > 256:                              # poda: deja las ultimas ~256 tramas
        for k in sorted(s.sent)[:len(s.sent) - 256]:
            del s.sent[k]
    return True


def retransmit(s):
    """Si el dron sigue esperando un seq que ya mandamos (stream atascado por un paquete
    perdido), reenvialo. Es lo que DESATASCA el type-5 y permite que el AUTO_FLY pase.
    Igual que el _pump de send_command, pero el recv lo hace el hilo receptor."""
    gap = (s.seq - s.drone_next) & 0xffff
    if 0 < gap <= 0x8000 and s.drone_next in s.sent:
        s.sock.sendto(s.sent[s.drone_next], N.DRONE)


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
    seq = MapSequencer(build_sequence(args.defl), int(args.yaw_defl))   # traslacion + giros lazo cerrado
    d_thr = max(0, min(int(args.climb_thr), 640))      # tope: 1024+640=1664 (< max 1684)
    climb_stick = (1024, 1024, 1024 + d_thr, 1024)     # throttle arriba FUERTE para subir
    print("=" * 64)
    print("  mapflight.py  —  %s" % ("VUELO + GRABACION" if real else "DRY (graba en tierra, sin despegar)"))
    print("  defl=%d  cam=%.0fdeg  ascenso=+%d x%.0fs (techo %.1fm)  giros: izq90/der180/izq90"
          % (args.defl, args.cam_pitch, args.climb_thr, args.climb_secs, args.alt))
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

    st = {"vpkts": [], "vwrap": 0, "vlast": None, "max_vid": 0, "max_tel": 0,
          "osd": None, "gpitch": None, "stop": False}
    rx = threading.Thread(target=_receiver, args=(s, st), daemon=True)
    rx.start()

    t0 = time.time()
    ei = 0
    last_ack = last_stick = last_report = last_mode = last_auth = last_retx = last_gimbal = -1.0
    wctr = 0xA000; mdseq = 0xd000; adseq = 0xc000
    takeoff_sent = False
    pre_to_reported = False        # ¿ya imprimimos el OSD pre-despegue? (una vez)
    auto_fly_mb = None             # frame AUTO_FLY pendiente (se reintenta hasta entrar en ventana)
    climbed = False                # ¿ya subimos a la altura de mapeo?
    climb_push_start = None        # t en que EMPEZO el empuje de throttle (tras estabilizar)
    t_pat = None                   # t (del reloj) en que empezo el patron (tras el ascenso)
    landing = False
    land_start = None
    t_takeoff = args.tvideo
    # fin: DRY corre 'tmax' s; FLY corre hasta takeoff+cap+aterrizaje
    end_dry = min(args.tmax, 40.0)
    try:
        while True:
            t = time.time() - t0
            # 0) retransmision: si el stream type-5 se atasco por un paquete perdido,
            #    desatascarlo reenviando el seq que el dron aun espera. SIN esto un solo
            #    drop mata el control y el AUTO_FLY nunca arma (era el bug del despegue).
            if t - last_retx >= 0.02:
                retransmit(s); last_retx = t
            # 1) replay del init de la app (arranca el video), respetando la ventana. En VUELO
            #    se DETIENE 1s antes del despegue: asi la ventana type-5 queda LIMPIA para que
            #    el AUTO_FLY y los sticks pasen (el video ya se sostiene con el ACK type-0x04).
            if (not real) or t < t_takeoff - 6.0:      # SETTLE limpio de 6s antes del despegue
                while ei < len(events) and events[ei][0] <= t:
                    if not raw_send(s, events[ei][1]):     # ventana llena: reintentar este
                        break                               # evento luego (mantiene el ORDEN)
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
                    if not pre_to_reported:
                        o = st["osd"]
                        if o:
                            why = N.START_FAIL_ENUM.get(o["start_fail_reason"], "0x%02x?" % o["start_fail_reason"])
                            print(">>> OSD pre-despegue: estado=%s motores=%s en_tierra=%s | MOTIVO NO-ARRANQUE: %s"
                                  % (N.FLYC_STATE_ENUM.get(o["flyc_state"], "?"), o["motor_on"], o["on_ground"], why), flush=True)
                        else:
                            print(">>> OSD pre-despegue: NO recibido (FC no nos empuja OSD = no enganchado)", flush=True)
                        pre_to_reported = True
                    # el AUTO_FLY DEBE entrar EN la ventana. Se construye una vez (contadores
                    # estables) y se REINTENTA cada vuelta; el retransmit desatasca si hace falta.
                    if auto_fly_mb is None:
                        auto_fly_mb = N.wrap_5101(wctr, N.funcctrl_frame(mdseq, N.AUTO_FLY))
                        wctr = (wctr + 1) & 0xffffffff; mdseq = (mdseq + 1) & 0xffff
                    if raw_send(s, auto_fly_mb):
                        print(">>> AUTO_FLY (despegue) ENVIADO en ventana en t+%.1f" % t, flush=True)
                        takeoff_sent = True
                if takeoff_sent:
                    t_air = t - t_takeoff
                    h = st["osd"]["height_m"] if st["osd"] else 0.0
                    # --- fase CLIMB: empujar throttle FUERTE y SOSTENIDO >= --climb-secs, PERO
                    #     solo tras estabilizar el auto-despegue (altura valida ~0.7m). Subir a
                    #     ciegas durante el auto-despegue arriesgaria pasarse. Para en: empuje
                    #     cumplido, O techo --alt (guarda), O backstop si nunca estabiliza.
                    if not climbed and not landing:
                        if h >= 0.3 and climb_push_start is None:
                            climb_push_start = t          # auto-despegue estabilizado -> a empujar
                        pushed = (t - climb_push_start) if climb_push_start is not None else 0.0
                        if (climb_push_start is not None and pushed >= args.climb_secs) \
                                or h >= args.alt or t_air > args.climb_max:
                            climbed = True; t_pat = t
                            print(">>> ascenso fin: alt=%.1fm (empuje %.1fs) -> patron de mapeo"
                                  % (h, pushed), flush=True)
                    if landing:
                        sticks = F.THROTTLE_MIN
                        if st["max_vid"] and (t - land_start) > 14.0:
                            break
                    elif not climbed:
                        # empuja SOLO con altura valida (>=0.3); si no, deja al FC su auto-despegue
                        sticks = climb_stick if h >= 0.3 else NEUTRAL
                    else:
                        # fase MAP: secuenciador (traslacion lazo abierto + giros lazo cerrado)
                        yaw = st["osd"]["yaw"] if st["osd"] else None
                        sticks = seq.sticks(t, yaw)
                        # aterriza al COMPLETAR la secuencia, o si se rebasa el tope --cap
                        if seq.done or (t - t_pat) >= args.cap:
                            landing = True; land_start = t
                            print(">>> patron %s -> ATERRIZANDO (throttle-min)"
                                  % ("completo" if seq.done else "cortado por tope --cap"), flush=True)
                            sticks = F.THROTTLE_MIN
                else:
                    sticks = NEUTRAL
            # 4) NUESTROS sticks (bare, 20Hz). Modo/autoridad/sub13 vienen del replay; en
            #    vuelo real reforzamos modo (wrapped, 10Hz) + autoridad (bare, 1Hz) como flight.py.
            if t - last_stick >= 0.05:
                _send_stick(s, sticks); last_stick = t
            if real:                                   # modo+autoridad DESDE EL SUELO (settle
                #                                        continuo; el FC lo necesita para armar)
                if t - last_mode >= 0.1:
                    # avanza los contadores SOLO si el frame entro en ventana (si no, se
                    # reintenta con el mismo contador -> canal 0x51/01 sin huecos)
                    if raw_send(s, N.wrap_5101(wctr, N.mode_frame(mdseq))):
                        wctr = (wctr + 1) & 0xffffffff; mdseq = (mdseq + 1) & 0xffff
                    last_mode = t
                if t - last_auth >= 1.0:
                    if raw_send(s, N.authority_frame(adseq, int(time.time()), 0x02)):
                        adseq = (adseq + 1) & 0xffff
                    last_auth = t
            # 4b) CAMARA: apuntar a --cam-pitch en lazo cerrado (gpitch del OSD gimbal).
            #     0x04/0x01 velocidad envuelta: 1024=quieta, <1024 baja, >1024 sube. Corre
            #     siempre (tambien en DRY, para validar en tierra que la camara baja).
            if t - last_gimbal >= 0.15:
                gp = st.get("gpitch")
                if gp is None:
                    vp = 1024                             # sin lectura aun: no mover
                else:
                    err = args.cam_pitch - gp             # >0 subir, <0 bajar
                    if abs(err) <= 2.0:
                        vp = 1024                         # llegado: HOLD
                    else:
                        mag = min(400, max(130, abs(err) * 40))
                        vp = 1024 + (mag if err > 0 else -mag)
                if raw_send(s, N.wrap_5101(wctr, N.gimbal_control_frame(mdseq, int(vp)))):
                    wctr = (wctr + 1) & 0xffffffff; mdseq = (mdseq + 1) & 0xffff
                last_gimbal = t
            # 5) reporte
            if t - last_report >= 1.0:
                if not real:            phase = "DRY"
                elif landing:           phase = "LAND"
                elif not takeoff_sent:  phase = "GROUND"
                elif not climbed:       phase = "CLIMB"
                else:                   phase = "MAP"
                o = st["osd"]
                mot = o["motor_on"] if o else "?"
                # altura + velocidad horizontal + angulo de camara: para VER (no adivinar).
                # vgx/vgy en marco MUNDO (cuantizados 0.1 m/s); util para calibrar --defl.
                alt = ("%.1fm" % o["height_m"]) if o else "?"
                spd = ("%.1f" % (o["vgx"] ** 2 + o["vgy"] ** 2) ** 0.5) if o else "?"
                cam = ("%.0fdeg" % st["gpitch"]) if st.get("gpitch") is not None else "?"
                yaw = ("%.0f" % o["yaw"]) if o else "?"     # heading: para VER los giros cerrar
                print("  t+%5.1f [%s] video=%d pkts, mot=%s alt=%s vH=%s cam=%s yaw=%s"
                      % (t, phase, len(st["vpkts"]), mot, alt, spd, cam, yaw), flush=True)
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
    ap.add_argument("--cap", type=float, default=60.0,
                    help="TOPE de seguridad del patron (s). Normalmente el patron termina solo "
                         "al completar la secuencia (los giros son lazo cerrado, duracion variable)")
    ap.add_argument("--defl", type=float, default=250.0,
                    help="deflexion del stick sobre el centro (1024) en la TRASLACION. 130=casi "
                         "no traslada, 250=visible (default), 350=amplio. Tope 500. Subir para "
                         "mas paralaje (necesita mas espacio); bajar si el cuarto es chico")
    ap.add_argument("--yaw-defl", dest="yaw_defl", type=float, default=600.0,
                    help="deflexion del stick de YAW en los giros (separada de --defl; el Neo "
                         "gira lento, ~6deg/s a 250). Default 600 (fuerte). Tope 640")
    ap.add_argument("--alt", type=float, default=1.5,
                    help="TECHO de seguridad del ascenso (m). El ascenso empuja throttle >= "
                         "--climb-secs, pero PARA si alcanza esta altura. Cuidado con el techo real")
    ap.add_argument("--climb-thr", dest="climb_thr", type=float, default=450.0,
                    help="fuerza del throttle de subida sobre 1024 (el auto-despegue resiste "
                         "empujes timidos; +220 no subio). Default +450. Tope +640")
    ap.add_argument("--climb-secs", dest="climb_secs", type=float, default=8.0,
                    help="segundos que se SOSTIENE el throttle arriba (tras estabilizar el "
                         "auto-despegue). El ascenso del Neo es lento -> min 8s")
    ap.add_argument("--climb-max", dest="climb_max", type=float, default=16.0,
                    help="backstop: si nunca estabiliza la altura, procede al patron a los N s")
    ap.add_argument("--cam-pitch", dest="cam_pitch", type=float, default=-45.0,
                    help="angulo de camara en grados: 0=frente, negativo=abajo. -45=piso+muebles "
                         "(recomendado para mapear), -90=recto al piso")
    ap.add_argument("--out", default="map_video.h265", help="archivo de video de salida")
    ap.add_argument("--decode", metavar="FILE", default=None, help="decodificar un .h265 (usa el .venv)")
    args = ap.parse_args()
    if args.decode:
        V.decode(args.decode)
    else:
        run(args)


if __name__ == "__main__":
    main()
