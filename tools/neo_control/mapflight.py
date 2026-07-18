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
                      + giros de yaw con PID (cobertura), BARRIENDO la camara con su PID de
                      velocidad para escanear las zonas -> aterriza. Los flags son la confirmacion.

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
import yaw_pid as YP        # reusa el PID de yaw validado en EXP-035/036 (YawPID/YawGate/rampa)
import gimbal_pid as GP      # reusa el PID de VELOCIDAD del gimbal (EXP-038) para el barrido
from sysid_gimbal import cmd_for_rate, MAX_CMD as GMAX, CENTER as GCEN   # inversion zona-muerta+expo

PCAP_DEFAULT = "C:\\Users\\santi\\Desktop\\DJI project\\Novena captura.pcap"

# --- Patron de vuelo (suave, simetrico, da PARALAJE para SLAM). Deflexion via --defl. ---
# 130 = casi no traslada (interior conservador); ~250 = traslacion visible; ~350 = amplio.
# El paralaje para SLAM NECESITA traslacion real, asi que el default sube a 250. Tope 500.
def _mv(dr=0, dp=0, dyaw=0):
    return (1024 + dr, 1024 + dp, 1024, 1024 + dyaw)
NEUTRAL = F.NEUTRAL

# Pasos de la secuencia de mapeo. Dos tipos:
#   ("move", sticks, secs) -> mantiene 'sticks' 'secs' segundos (traslacion/pausa, LAZO ABIERTO)
#   ("turn", grados)       -> giro de LAZO CERRADO con el PID de yaw (EXP-035/036, reusa
#                             yaw_pid.YawPID): gira 'grados' relativos al rumbo del OSD al
#                             empezar el paso (grados>0 = DERECHA, ch3+, yaw sube; <0 = IZQUIERDA).
YAW_TOL    = 3.0       # grados: el PID sostiene mucho mejor que el bang-bang viejo (era 8)
YAW_SETTLE = 0.5       # s dentro de tolerancia (Y con la rampa ya terminada) para cerrar el giro
TS_YAW     = YP.TS     # 0.1 s: cadencia del PID (= la del OSD); ZOH entre recalculos
# Backstop por si la telemetria falla: tiempo de rampa (|deg|/ramp) + margen holgado. Con
# rampa=25, 90deg tardan ~3.6s y 180deg ~7.2s (giro SUAVE), no el bang-bang a ~49deg/s.
def _turn_timeout(deg, ramp):
    slew = abs(deg) / (ramp if ramp else YP.MAX_RATE)
    return slew + 8.0

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
    """Ejecuta la secuencia de mapeo paso a paso.
      - 'move': por tiempo (LAZO ABIERTO), sin cambios.
      - 'turn': LAZO CERRADO con el PID de yaw de EXP-035/036 (yaw_pid.YawPID + YawGate + rampa
        del setpoint). Al empezar el paso fija el objetivo ABSOLUTO = wrap180(yaw_actual + grados)
        y el PID escribe el stick de yaw directamente (mismas ganancias y unidades que yaw_pid;
        no se invierte el expo, va dentro del modelo). La rampa (--yaw-ramp) mantiene el lazo
        FUERA de saturacion -> giro suave a velocidad ~constante (ideal para cobertura/SLAM) y
        sin ciclo limite. El giro se da por cerrado cuando la rampa YA llego al objetivo Y
        |error| <= YAW_TOL sostenido YAW_SETTLE s; el timeout es respaldo si falla la telemetria.
    done=True al terminar toda la secuencia."""
    def __init__(self, sequence, yaw_defl, kp, ki, kd, ramp):
        self.seq = sequence
        self.umax = max(0, min(int(yaw_defl), 660))    # saturacion del stick de yaw (rango +-660)
        self.gains = (kp, ki, kd)
        self.ramp = ramp
        self.i = 0
        self.step_start = None
        self.done = False
        self._turn_reset()

    def _turn_reset(self):
        self.pid = None            # se crea con la 1a lectura de yaw valida del paso
        self.gate = None
        self.sp = None             # objetivo absoluto del giro
        self.sp_cmd = None         # setpoint rampeado
        self.u_hold = 0.0          # ultimo stick calculado (ZOH entre recalculos del PID)
        self.last_pid = None
        self.in_tol = None         # t desde el que |error| <= YAW_TOL de forma continua

    def _advance(self):
        self.i += 1; self.step_start = None; self._turn_reset()

    def sticks(self, t, yaw):
        """Sticks para el paso actual; avanza al terminarlo. NEUTRAL cuando ya acabo todo."""
        if self.i >= len(self.seq):
            self.done = True
            return NEUTRAL
        step = self.seq[self.i]
        if self.step_start is None:                    # primera iteracion del paso
            self.step_start = t
        if step[0] == "move":
            _, sticks, secs = step
            if t - self.step_start >= secs:
                self._advance()
            return sticks
        # ("turn", grados): lazo cerrado con el PID de yaw (EXP-035/036)
        _, deg = step
        if yaw is None:                                # sin telemetria aun: no muevas el yaw
            if (t - self.step_start) > _turn_timeout(deg, self.ramp):
                self._advance()
            return NEUTRAL
        if self.pid is None:                           # arranca el giro con la 1a lectura valida
            kp, ki, kd = self.gains
            self.pid = YP.YawPID(kp, ki, kd, umax=self.umax)
            self.gate = YP.YawGate()
            self.sp = YP.wrap180(yaw + deg)            # objetivo ABSOLUTO relativo al rumbo actual
            self.sp_cmd = None                         # la rampa arranca en el yaw actual
            self.last_pid = t - TS_YAW                 # fuerza un recalculo inmediato
        # recalcula el PID a ~10 Hz (cadencia del OSD); ZOH del stick entre recalculos
        if t - self.last_pid >= TS_YAW:
            dt = t - self.last_pid
            yaw_ok, _ = self.gate.feed(yaw, t)         # descarta rumbos fisicamente imposibles
            if self.ramp:
                if self.sp_cmd is None:
                    self.sp_cmd = yaw_ok
                d = YP.wrap180(self.sp - self.sp_cmd)
                step_max = self.ramp * dt
                self.sp_cmd = YP.wrap180(self.sp_cmd + max(-step_max, min(step_max, d)))
                target = self.sp_cmd
            else:
                target = self.sp
            u, _, _, _, _ = self.pid.step(target, yaw_ok)
            self.u_hold = u
            self.last_pid = t
            # cierre SOLO cuando la rampa ya llego al objetivo (si no, el error chico a media
            # rampa cerraria el giro corto) Y el error al objetivo FINAL es pequeño y sostenido
            ramp_done = (not self.ramp) or abs(YP.wrap180(self.sp - self.sp_cmd)) < 0.5
            if ramp_done and abs(YP.wrap180(self.sp - yaw_ok)) <= YAW_TOL:
                if self.in_tol is None:
                    self.in_tol = t
            else:
                self.in_tol = None
        settled = self.in_tol is not None and (t - self.in_tol) >= YAW_SETTLE
        if settled or (t - self.step_start) > _turn_timeout(deg, self.ramp):
            self._advance()
            return NEUTRAL
        y = int(round(max(-self.umax, min(self.umax, self.u_hold))))
        return (1024, 1024, 1024, 1024 + y)            # ch3+ der (yaw sube), ch3- izq


# --- barrido de camara (tilt) con el PID de VELOCIDAD del gimbal (EXP-038) ---
# "siempre escanear moviendo el gimbal para cubrir las zonas": se barre a velocidad
# ~CONSTANTE entre [lo, hi] reusando su RatePID + la inversion zona-muerta/expo
# (cmd_for_rate). Reversa al llegar a cada extremo. Rate constante = video suave = mejor
# tracking de features para SLAM. NO usa lazo de ANGULO (aun sin tunear); el rate PID + la
# reversa por angulo bastan para recorrer el rango. Topes fisicos del gimbal: -90..+60.
GIMBAL_LO_DEF, GIMBAL_HI_DEF = -75.0, 0.0     # barrido: del suelo (-75) al horizonte (0)
GIMBAL_RATE_DEF = 12.0                          # deg/s del barrido (suave; fondo fisico 26.2)
GIMBAL_MARGIN = 5.0                             # deg antes del extremo para invertir


class GimbalScanner:
    """Barre el tilt de la camara a velocidad constante entre [lo,hi] con el PID de velocidad
    del usuario (gimbal_pid.RatePID, EXP-038), tal cual. Devuelve el valor 0x04/0x01 (1024=quieta)."""
    def __init__(self, lo, hi, rate, margin=GIMBAL_MARGIN):
        self.lo, self.hi = min(lo, hi), max(lo, hi)
        self.rate = abs(rate)
        self.margin = margin
        self.pid = GP.RatePID()                 # su PID de velocidad, sin tocar
        self.dir = -1
        self.g_prev = None
        self.t_prev = None
        self.u_hold = 0.0

    def value(self, t, gpitch):
        """Comando de velocidad del gimbal para este instante. gpitch None -> no mover."""
        if gpitch is None:
            return GCEN
        if self.g_prev is None:                 # 1a lectura: elige direccion hacia el rango
            self.g_prev, self.t_prev = gpitch, t
            self.dir = 1 if gpitch < (self.lo + self.hi) / 2 else -1
            return GCEN
        dt = t - self.t_prev
        if dt <= 0:                             # ZOH si no hay muestra nueva
            return int(GCEN + max(-GMAX, min(GMAX, cmd_for_rate(self.u_hold))))
        rate_med = (gpitch - self.g_prev) / dt  # diferencia HACIA ATRAS (causal), como EXP-038
        self.g_prev, self.t_prev = gpitch, t
        if self.dir > 0 and gpitch >= self.hi - self.margin:      # reversa en los extremos
            self.dir = -1
        elif self.dir < 0 and gpitch <= self.lo + self.margin:
            self.dir = 1
        u = self.pid.step(self.dir * self.rate, rate_med, dt)[0]   # PID sobre error de velocidad
        self.u_hold = u
        return int(GCEN + max(-GMAX, min(GMAX, cmd_for_rate(u))))  # rate_cmd -> stick (inv. expo)


def _point_value(gpitch, target):
    """Apunta el gimbal a 'target' deg con control proporcional simple (parking pre-mapeo)."""
    if gpitch is None:
        return GCEN
    err = target - gpitch                        # >0 subir, <0 bajar
    if abs(err) <= 2.0:
        return GCEN                              # llegado: HOLD
    mag = min(400, max(130, abs(err) * 40))
    return GCEN + (mag if err > 0 else -mag)


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


def _decode_thread(st):
    """VIDEO EN VIVO (--preview): DECODIFICA en un hilo aparte con un CodecContext HEVC
    PERSISTENTE de PyAV y deja el ultimo frame BGR en st['pv_frame']; la VENTANA la pinta el
    HILO PRINCIPAL (GUI de OpenCV solo fiable ahi en Windows). No toca el control (solo LEE
    st['vpkts']).

    CLAVE (lo que costo dar con ello): el flag **'showall'** (FFmpeg 8.1.2 / PyAV 18) hace que
    el decoder EMITA los frames corruptos. Nuestro stream en vivo pierde paquetes; sin showall
    PyAV los DESCARTA y salian ~0 frames (medido: 299 vs 1852 con el flag). Se alimenta el
    stream REENSAMBLADO de forma INCREMENTAL (cursor de bytes): el CodecContext mantiene estado
    -> cada frame se decodifica UNA sola vez -> ~14x tiempo real, sin relag. (El intento previo
    con cv2.VideoCapture redecodificaba el archivo entero cada vez y crecia sin fin = 'muy lento'.)"""
    import time as _t
    try:
        import av
        av.logging.set_level(av.logging.PANIC)   # silencia el flood de 'PPS out of range'/'POC' etc.
    except Exception as e:
        print("!! --preview: falta PyAV (%s). Corre via neo.ps1 (.venv)." % e, flush=True)
        st["pv_err"] = True
        return
    try:
        import cv2                                # solo para resize (el imshow lo hace main)
    except Exception:
        cv2 = None
    ctx = av.CodecContext.create("hevc", "r")
    ctx.options = {"flags2": "+showall", "err_detect": "ignore_err"}   # emitir frames corruptos
    cursor = 0
    while not st["stop"]:
        es, _, _ = V._reassemble_frames(list(st["vpkts"]))   # copia -> no toca la lista compartida
        if len(es) > cursor:
            try:
                for pkt in ctx.parse(es[cursor:]):           # el parser bufferiza NALs parciales
                    for fr in ctx.decode(pkt):
                        img = fr.to_ndarray(format="bgr24")
                        if cv2 is not None:
                            img = cv2.resize(img, (960, 540))
                        st["pv_frame"] = img
                        st["pv_n"] = st.get("pv_n", 0) + 1
            except Exception:
                pass                                          # frame malo -> seguir
            cursor = len(es)
        _t.sleep(0.2)


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
    seq = MapSequencer(build_sequence(args.defl), int(args.yaw_defl),   # traslacion + giros lazo cerrado
                       args.yaw_kp, args.yaw_ki, args.yaw_kd, args.yaw_ramp)
    scanner = GimbalScanner(args.gimbal_lo, args.gimbal_hi, args.gimbal_rate)   # barrido de camara
    d_thr = max(0, min(int(args.climb_thr), 640))      # tope: 1024+640=1664 (< max 1684)
    climb_stick = (1024, 1024, 1024 + d_thr, 1024)     # throttle arriba FUERTE para subir
    print("=" * 64)
    print("  mapflight.py  —  %s" % ("VUELO + GRABACION" if real else "DRY (graba en tierra, sin despegar)"))
    print("  defl=%d  ascenso a %.1fm (+%d x%.0fs, tope seg. %.1fm)  giros: izq90/der180/izq90"
          % (args.defl, args.alt, args.climb_thr, args.climb_secs, args.alt_max))
    print("  giros: PID yaw Kp=%.1f Ki=%.1f Kd=%.2f rampa=%.0f deg/s (lazo cerrado, EXP-035/036)"
          % (args.yaw_kp, args.yaw_ki, args.yaw_kd, args.yaw_ramp))
    print("  camara: BARRIDO %.0f..%.0f deg @ %.0f deg/s con PID de velocidad (EXP-038)"
          % (args.gimbal_lo, args.gimbal_hi, args.gimbal_rate))
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
          "osd": None, "gpitch": None, "stop": False, "pv_frame": None, "pv_n": 0}
    rx = threading.Thread(target=_receiver, args=(s, st), daemon=True)
    rx.start()
    # video EN VIVO (--preview): decodifica en un hilo aparte; la ventana la pinta el hilo
    # principal (GUI de OpenCV solo fiable ahi en Windows). cv2 se importa aqui.
    pv_cv2 = None
    pv_win = "Neo LIVE (preview)"
    pv_shown = False
    if args.preview:
        try:
            import cv2 as pv_cv2
        except Exception as e:
            print("!! --preview: no hay cv2 en este python (%s). Corre via neo.ps1 (.venv)." % e, flush=True)
            pv_cv2 = None
        threading.Thread(target=_decode_thread, args=(st,), daemon=True).start()

    t0 = time.time()
    ei = 0
    last_ack = last_stick = last_report = last_mode = last_auth = last_retx = last_gimbal = -1.0
    last_pv = -1.0
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
                        # fase MAP: secuenciador (traslacion lazo abierto + giros con PID de yaw)
                        yaw = st["osd"]["yaw"] if st["osd"] else None
                        sticks = seq.sticks(t, yaw)
                        # aterriza si: la altura supera el tope de seguridad, se COMPLETA la
                        # secuencia, o se rebasa el tope de tiempo --cap
                        if h > args.alt_max:
                            landing = True; land_start = t
                            print(">>> ALTURA %.1fm > tope %.1fm -> ATERRIZANDO (seguridad)"
                                  % (h, args.alt_max), flush=True)
                            sticks = F.THROTTLE_MIN
                        elif seq.done or (t - t_pat) >= args.cap:
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
            # 4b) CAMARA (0x04/0x01, 1024=quieta). En MAPEO (y en DRY, para validar en tierra):
            #     BARRIDO a velocidad constante con el PID del gimbal (EXP-038) para escanear las
            #     zonas. Antes del mapeo (suelo/ascenso) o aterrizando: apunta a --cam-pitch.
            if t - last_gimbal >= 0.1:
                gp = st.get("gpitch")
                scanning = (not real) or (climbed and not landing)
                vp = scanner.value(t, gp) if scanning else _point_value(gp, args.cam_pitch)
                if raw_send(s, N.wrap_5101(wctr, N.gimbal_control_frame(mdseq, int(vp)))):
                    wctr = (wctr + 1) & 0xffffffff; mdseq = (mdseq + 1) & 0xffff
                last_gimbal = t
            # 4c) PREVIEW: pinta el ultimo frame decodificado (por _decode_thread) EN EL HILO
            #     PRINCIPAL. imshow+waitKey(1) ~1-2ms cada 100ms: despreciable para el control.
            if args.preview and pv_cv2 is not None and t - last_pv >= 0.1:
                fr = st["pv_frame"]
                if fr is not None:
                    if not pv_shown:
                        pv_cv2.namedWindow(pv_win, pv_cv2.WINDOW_NORMAL)
                        pv_cv2.resizeWindow(pv_win, 960, 540)
                        pv_shown = True
                        print(">>> preview de video EN VIVO abierto (ventana '%s')" % pv_win, flush=True)
                    pv_cv2.imshow(pv_win, fr)
                    pv_cv2.waitKey(1)
                last_pv = t
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
        if pv_cv2 is not None and pv_shown:
            try:
                pv_cv2.destroyAllWindows()
                pv_cv2.waitKey(1)
            except Exception:
                pass
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
                    help="SATURACION del stick de yaw en los giros (umax del PID; el rango real "
                         "es +-660). Con --yaw-ramp el lazo casi no satura. Default 600, tope 660")
    ap.add_argument("--yaw-kp", dest="yaw_kp", type=float, default=YP.KP,
                    help="Kp del PID de yaw de los giros (EXP-035). Default el del usuario")
    ap.add_argument("--yaw-ki", dest="yaw_ki", type=float, default=0.0,
                    help="Ki del PID de yaw. Default 0: la planta YA es integrador, la I solo "
                         "cuesta fase y reaviva el ciclo limite (EXP-036). RECOMENDADO 0")
    ap.add_argument("--yaw-kd", dest="yaw_kd", type=float, default=YP.KD,
                    help="Kd del PID de yaw (sobre la MEDIDA). Default el del usuario")
    ap.add_argument("--yaw-ramp", dest="yaw_ramp", type=float, default=25.0, metavar="DEG_S",
                    help="rampa el objetivo de yaw a DEG_S deg/s -> giro suave a velocidad "
                         "~constante, sin saturar ni ciclo limite (EXP-036). 0 = escalon. "
                         "Sube a ~40 para giros mas rapidos (el dron topa en 49.5)")
    ap.add_argument("--alt", type=float, default=2.0,
                    help="altura de MAPEO objetivo (m). El ascenso empuja throttle >= --climb-secs "
                         "pero PARA si alcanza esta altura. Default 2.0 (techo del cuarto ~3.24m)")
    ap.add_argument("--alt-max", dest="alt_max", type=float, default=2.8,
                    help="TOPE DURO de altura (m): si en mapeo la altura lo supera, ATERRIZA. "
                         "Seguridad contra deriva hacia el techo. Default 2.8")
    ap.add_argument("--climb-thr", dest="climb_thr", type=float, default=450.0,
                    help="fuerza del throttle de subida sobre 1024 (el auto-despegue resiste "
                         "empujes timidos; +220 no subio). Default +450. Tope +640")
    ap.add_argument("--climb-secs", dest="climb_secs", type=float, default=10.0,
                    help="segundos que se SOSTIENE el throttle arriba (tras estabilizar el "
                         "auto-despegue). Para 2m el ascenso lento del Neo necesita ~10s")
    ap.add_argument("--climb-max", dest="climb_max", type=float, default=20.0,
                    help="backstop: si nunca estabiliza la altura, procede al patron a los N s")
    ap.add_argument("--cam-pitch", dest="cam_pitch", type=float, default=-45.0,
                    help="angulo de PARKING de la camara (deg) antes del mapeo/al aterrizar; "
                         "0=frente, negativo=abajo. En mapeo NO se usa: ahi la camara BARRE")
    ap.add_argument("--gimbal-lo", dest="gimbal_lo", type=float, default=GIMBAL_LO_DEF,
                    help="angulo INFERIOR del barrido de camara (deg). Default -75 (hacia el suelo). "
                         "Tope fisico -90")
    ap.add_argument("--gimbal-hi", dest="gimbal_hi", type=float, default=GIMBAL_HI_DEF,
                    help="angulo SUPERIOR del barrido (deg). Default 0 (horizonte). Tope fisico +60. "
                         "Sube (p.ej. +20) para incluir la parte alta de las paredes")
    ap.add_argument("--gimbal-rate", dest="gimbal_rate", type=float, default=GIMBAL_RATE_DEF,
                    help="velocidad del barrido de camara (deg/s). Default 12 (suave); fondo "
                         "fisico 26.2. Mas lento = video mas nitido, mas rapido = mas cobertura/s")
    ap.add_argument("--preview", action="store_true",
                    help="muestra el VIDEO EN VIVO en una ventana durante la corrida (decode PyAV "
                         "incremental en hilo aparte, no toca el control; flag 'showall' para "
                         "emitir frames aunque haya perdida de paquetes). Requiere PyAV+cv2 -> "
                         "corre via neo.ps1 (usa el .venv). Pruebalo primero en DRY (en tierra)")
    ap.add_argument("--out", default="map_video.h265", help="archivo de video de salida")
    ap.add_argument("--decode", metavar="FILE", default=None, help="decodificar un .h265 (usa el .venv)")
    args = ap.parse_args()
    if args.decode:
        V.decode(args.decode)
    else:
        run(args)


if __name__ == "__main__":
    main()
