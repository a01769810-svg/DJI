#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
flight.py — Vuelo del DJI Neo (EXP-024). Wrapper UDP fiable (EXP-018) + envoltorio
0x51/0x01 (EXP-023) + DESPEGUE REAL via FunctionControl (EXP-024).

CORRECCION EXP-024: el despegue NO es 0x03/0xda (eso es Detection/housekeeping); es
FunctionControl 0x03/0x2a:01 AUTO_FLY, y el aterrizaje 0x03/0x2a:02 AUTO_LANDING,
ambos ENVUELTOS en 0x51/0x01. Confirmado: 0x03/0x2a:01 aparece solo en sesiones con
vuelo real, con ack DN=00 del dron.

EXP-025: antes del despegue hay que ENGANCHAR la sesion con el handshake de
suscripcion 0x51 (0x51/02+06+08 con el serial del dron + stream 0x51/13). Sin el,
el FC ignora todo; con el, el FC nos procesa y reporta motores permitidos.

Secuencia (validada byte a byte por analysis/validate_arm.py contra Quinta/Octava):
  HELLO -> reliable-UDP -> init (8 frames) -> SUSCRIPCION 0x51 (engancha al FC)
        -> modo Manual (envuelto) + NEUTRO + autoridad [+ stream 0x51/13 continuo]
        -> [--fly] AUTO_FLY (0x03/0x2a:01, envuelto) -> hover NEUTRO
        -> ATERRIZAJE: throttle-min sostenido (EXP-027; AUTO_LANDING no baja) o --land-mode auto
  Opcional --detection-prep: manda el housekeeping Detection/params del arranque
  (0x03/0xf8, 0x03/0x34, 0x03/0x3c, 0x0d/0x03, 0x03/0xda). NO se asume precondicion.

MODOS:
  (sin flags)         DRY RUN: init + modo + NEUTRO + autoridad, SIN AUTO_FLY. Confirma
                      que el dron acepta la secuencia (ventana RX avanza). SEGURO interior.
  --fly --armed-ok    VUELO REAL: manda AUTO_FLY. REQUIERE los DOS flags + tecleo VOLAR.

Coordenada de autoridad var-03 (privacidad):
  --lat / --lon en grados decimales, en runtime, NO se guardan. Sin ellas => var-02.

SEGURIDAD (obligatoria para --fly):
  - GPS NO es requisito (el Neo vuela por vision/IR). SI lo es el sensor de abajo:
    dron PLANO sobre piso normal, no reflejante, sensores IR/vision despejados.
  - Area despejada SIN personas ni mascotas cerca (auto-despegue ~1.2 m). Supervisado.
  - Helices firmes. DJI Fly con failsafe = ATERRIZAR configurado de antemano.
  - Ctrl+C = ATERRIZAJE por throttle-min (descend). Corte de emergencia real = BOTON del dron.

USO:
  python flight.py                                    # DRY RUN seguro (sin AUTO_FLY)
  python flight.py --fly --armed-ok                   # VUELO REAL (exterior/supervisado)
  python flight.py --fly --armed-ok --lat .. --lon .. # VUELO REAL con autoridad var-03
"""
import argparse, sys, time, threading, socket
from datetime import datetime
import neo_udp as N


class KeepAlive:
    """Mantiene viva la sesion UDP fiable enviando el hello keepalive en un hilo de
    fondo durante PAUSAS (input del usuario, cuenta atras). Sin esto, un silencio de
    varios segundos hace que el dron DESCARTE la sesion (la ventana RX se congela en
    el seed) y todo comando posterior se ignora. Bug que invalidaba todos los --fly."""
    def __init__(self, sess, period=0.3):
        self.s = sess; self.period = period
        self._stop = threading.Event(); self._t = None
    def __enter__(self):
        def run():
            while not self._stop.wait(self.period):
                try:
                    self.s.keepalive()
                except Exception:
                    pass
        self._t = threading.Thread(target=run, daemon=True); self._t.start()
        return self
    def __exit__(self, *a):
        self._stop.set()
        if self._t:
            self._t.join(timeout=1.0)
        return False

# --- Init verbatim capturado del vuelo real (Quinta), enviado como type-5 ---
INIT = [bytes.fromhex(h) for h in [
    "550d0433020e95e5400001981f",
    "551204c7022899e54000b70101000c0094e0",
    "552204ea02039ee540114a00000000000088d3c0000000000088d3c05f3b546af603",
    "550e04660228aae54000510654fa",
    "552504840207cde5400793012b230032303230656534642d366163612d343636662d000e2f",
    "553304c2eee90200405134000402000032303230656534642d366163612d343636662d00000000000000000000000000006b21",
    "55430474cec80000001837010200000000000000000000000000010000000000000000000000000000000000000000000000000000000000000000000000000000b506",
    "553d041ecec8000040183c0d000400010500000000000000000102000000000000000000000000010100000000000000000000000000000000000033a4",
]]

def _V(r, p, th, y):
    return (((r & 0x7ff) | ((p & 0x7ff) << 11) | ((th & 0x7ff) << 22) | ((y & 0x7ff) << 33))
            ).to_bytes(6, "little")

NEUTRAL = (1024, 1024, 1024, 1024)     # roll,pitch,thr,yaw centrados => hover
THROTTLE_MIN = (1024, 1024, 364, 1024) # ch2 (throttle) al minimo => descenso vertical (EXP-027)

# --- MOVIMIENTO DIRECCIONAL (EXP-028). Deflexiones CONSERVADORAS para interior. ---
# Rango del stick 364..1684, centro 1024. Deflexion pequena = movimiento suave.
# El SIGNO (adelante vs atras, izq vs der) se CONFIRMA por telemetria (pitch/roll/vgx/vgy),
# no se asume: por eso las maniobras van y vuelven (una direccion y su opuesta).
D_YAW, D_PITCH, D_ROLL = 180, 150, 150
YAW_R   = (1024, 1024, 1024, 1024 + D_YAW)     # giro (ch3+)
YAW_L   = (1024, 1024, 1024, 1024 - D_YAW)     # giro (ch3-)
PITCH_F = (1024, 1024 + D_PITCH, 1024, 1024)   # cabeceo (ch1+)
PITCH_B = (1024, 1024 - D_PITCH, 1024, 1024)   # cabeceo (ch1-)
ROLL_R  = (1024 + D_ROLL, 1024, 1024, 1024)    # alabeo (ch0+)
ROLL_L  = (1024 - D_ROLL, 1024, 1024, 1024)    # alabeo (ch0-)


def fmt_telem(o, b=None):
    """Linea compacta de telemetria para logs de vuelo. La BATERIA viene del mensaje
    dedicado Battery Dynamic Data (b, 0x0d/0x02) que SI es fiable; el batt_remain del OSD
    del Neo es basura (contador, no %). El resto (altura/velocidad/actitud/sats) es del OSD."""
    bat = ("%d%% %.2fV" % (b["soc"], b["voltage_mv"] / 1000.0)) if b else "?"
    return ("bat=%s alt=%.1fm vel=(%.1f,%.1f,%.1f) act=(p%.0f r%.0f y%.0f) sats=%s motor=%s"
            % (bat, o["height_m"], o["vgx"], o["vgy"], o["vgz"],
               o["pitch"], o["roll"], o["yaw"], o.get("gps_nums", "?"), o["motor_on"]))

def deg_to_e6(d):
    """grados decimales -> int32 grados*1e6 (formato de la autoridad var-03)."""
    return int(round(d * 1_000_000))

class Flight:
    def __init__(self, sess, lat=None, lon=None):
        self.s = sess
        self.dseq = 0xe600
        self.hb = 0                       # contador del heartbeat 0x03/0xd7 (opcional)
        self.hb_started = False
        self.wdseq = 1                    # contador del canal 0x51/0x01 (transmision transparente)
        self.serial = None                # serial del dron (extraido en vivo, NO se hardcodea)
        self.sub_ctr = 2                  # contador del stream de suscripcion 0x51/0x13
        self.last_batt = None             # ultimo Battery Dynamic Data (0x0d/0x02) visto
        self.last_landed = False          # el ultimo _fly_loop con land_detect confirmo aterrizaje
        # autoridad var-03 solo si hay coordenada; si no, var-02
        self.auth_state = 0x03 if (lat is not None and lon is not None) else 0x02
        self.lat_e6 = deg_to_e6(lat) if lat is not None else 0
        self.lon_e6 = deg_to_e6(lon) if lon is not None else 0

    def _dseq(self):
        v = self.dseq; self.dseq = (self.dseq + 1) & 0xffff; return v

    def _wrapped(self, inner):
        """Envia un frame DUML por el canal 0x51/0x01 (armado/commit/params van asi)."""
        r = self.s.send_command(N.wrap_5101(self.wdseq, inner))
        self.wdseq = (self.wdseq + 1) & 0xffffffff
        return r

    # -- BARE (crudos, como la app): sticks, autoridad --
    def stick(self, r, p, th, y):
        # cola CORREGIDA (EXP-026): ...55 01 04 56 08 <contador u16 LE> 00*6.
        # El contador (timestamp ms) es lo que faltaba: el FC valida el stream de
        # control como vivo/monotono; sin el no somos 'controlador activo'.
        ctr = int(time.time() * 1000) & 0xffff
        mb = N.mb_frame(0x02, 0xa9, self._dseq(), 0x00, 0x01, 0x0a,
                        b"\x01\x0d\x00" + _V(r, p, th, y)
                        + b"\x40\x00\x02\x00\x00\x06\x55\x01\x04\x56\x08"
                        + ctr.to_bytes(2, "little") + b"\x00\x00\x00\x00\x00\x00")
        return self.s.send_command(mb)

    def authority(self):
        # ts = timestamp Unix real (el contador de la autoridad es la hora en segundos)
        ts = int(time.time())
        return self.s.send_command(
            N.authority_frame(self._dseq(), ts, self.auth_state, self.lat_e6, self.lon_e6))

    # -- ENVUELTOS en 0x51/0x01 (como la app): DESPEGUE/ATERRIZAJE, modo, GETs --
    def auto_fly(self):
        """DESPEGUE REAL (EXP-024): FunctionControl 0x03/0x2a:01 AUTO_FLY, envuelto.
        El dron responde DN 0x03/0x2a=00 (ack)."""
        return self._wrapped(N.funcctrl_frame(self._dseq(), N.AUTO_FLY))

    def auto_landing(self):
        """ATERRIZAJE: FunctionControl 0x03/0x2a:02 AUTO_LANDING, envuelto.
        OJO (EXP-026): NO hace descender al Neo (siguio flotando; latch
        function_command_state sin limpiar tras AUTO_FLY). Usar descend()."""
        return self._wrapped(N.funcctrl_frame(self._dseq(), N.AUTO_LANDING))

    def _fly_loop(self, sticks, secs, label="", land_detect=False, telem=True):
        """Loop de control generico (EXP-028): streamea 'sticks' (20Hz) manteniendo el
        enganche 0x51/13, el modo Manual, la autoridad y el keepalive, igual que el hover.
        DECODIFICA y muestra telemetria del OSD (bateria/altura/actitud/velocidad) ~2Hz.
        land_detect: corta al confirmar touchdown (en_tierra + motores off).
        Devuelve el ultimo OSD decodificado (dict) o None."""
        if label:
            print(label, flush=True)
        t0 = time.time()
        nt = {"stick": 0.0, "mode": 0.0, "auth": 0.0, "ka": 0.0, "sub": 0.0, "tel": 0.0}
        osd = None
        motor_seen = False               # ¿vimos motores encendidos en algun momento?
        self.last_landed = False
        while time.time() - t0 < secs:
            now = time.time()
            if self.serial and now >= nt["sub"]:
                self.sub13(); nt["sub"] = now + 0.2           # mantiene el enganche ~5Hz
            if now >= nt["mode"]:
                self.set_mode(); nt["mode"] = now + 0.1        # sigue en Manual
            if now >= nt["stick"]:
                self.stick(*sticks); nt["stick"] = now + 0.05  # sticks ~20Hz
            if now >= nt["auth"]:
                self.authority(); nt["auth"] = now + 1.0
            if now >= nt["ka"]:
                self.s.keepalive(); nt["ka"] = now + 0.5
            self.s.sock.settimeout(0.03)
            try:
                d, a = self.s.sock.recvfrom(65535)
            except (socket.timeout, BlockingIOError):
                d = None
            if d and a[0] == N.DRONE[0]:
                o = N.find_osd_general(d)
                if o:
                    osd = o
                b = N.find_battery_dynamic(d)
                if b:
                    self.last_batt = b
            if telem and osd and now >= nt["tel"]:
                print("    telem: %s" % fmt_telem(osd, self.last_batt), flush=True); nt["tel"] = now + 0.5
            # touchdown: el bit on_ground del Neo NO es fiable; usamos el apagado de motores
            # (motor_on True->False) tras haberlos visto encendidos = aterrizo y desarmo.
            if land_detect and osd:
                if osd["motor_on"]:
                    motor_seen = True
                elif motor_seen:
                    self.last_landed = True
                    break
        return osd

    def descend(self, secs):
        """ATERRIZAJE por throttle-min sostenido (EXP-027). Como AUTO_LANDING no baja al
        Neo pero el stream de control SI funciona (fue lo que probo el despegue), bajamos
        con el throttle al minimo y roll/pitch/yaw centrados = descenso vertical sin deriva.
        Lee el OSD y CORTA en cuanto los motores se apagan tras el aterrizaje (el bit
        on_ground del Neo no es fiable; ver _fly_loop). Devuelve True si confirmo el
        aterrizaje por apagado de motores; False si se agoto la ventana."""
        self._fly_loop(THROTTLE_MIN, secs, land_detect=True)
        return self.last_landed

    def maneuver(self, name, secs=2.0, brake=1.5, defl=None):
        """Maniobra direccional (EXP-028), en vuelo, tras el hover. La IDA y la VUELTA
        duran EXACTAMENTE lo mismo ('secs') con deflexion opuesta, para volver al inicio
        (lazo abierto: aproximado). Entre medias un centrado NEUTRO de 'brake' s frena.
        'defl' = magnitud del stick sobre 1024 (None => default por eje). Subirla para
        vencer el hold de posicion por vision del Neo (pitch/roll pequenos no trasladan).
        El signo real de cada eje se lee en la telemetria (yaw / pitch+vgx / roll+vgy)."""
        d = defl if defl is not None else {"yaw": D_YAW, "forward": D_PITCH,
                                           "roll": D_ROLL, "demo": 250}[name]
        d = max(0, min(int(d), 500))              # tope de seguridad (rango stick +-660)
        if name == "demo":
            # secuencia completa: izquierda, derecha, frente, atras, giro der, giro izq.
            seq = [
                ("roll IZQUIERDA (ch0-)", (1024 - d, 1024, 1024, 1024)),
                ("roll DERECHA (ch0+)",   (1024 + d, 1024, 1024, 1024)),
                ("pitch FRENTE (ch1+)",   (1024, 1024 + d, 1024, 1024)),
                ("pitch ATRAS (ch1-)",    (1024, 1024 - d, 1024, 1024)),
                ("yaw DERECHA (ch3+)",    (1024, 1024, 1024, 1024 + d)),
                ("yaw IZQUIERDA (ch3-)",  (1024, 1024, 1024, 1024 - d)),
            ]
            print("   DEMO (deflexion=%d, %.1fs por movimiento)" % (d, secs), flush=True)
            for lbl, sticks in seq:
                self._fly_loop(sticks,  secs,  label="   " + lbl)
                self._fly_loop(NEUTRAL, brake, label="   centro (freno)")
            return
        if name == "yaw":
            a, b = (1024, 1024, 1024, 1024 + d), (1024, 1024, 1024, 1024 - d)
            la, lb = "yaw (ch3+): giro derecha", "yaw (ch3-): giro izquierda (igual, vuelve)"
        elif name == "forward":
            a, b = (1024, 1024 + d, 1024, 1024), (1024, 1024 - d, 1024, 1024)
            la, lb = "pitch (ch1+): avance", "pitch (ch1-): retroceso (igual, vuelve)"
        elif name == "roll":
            a, b = (1024 + d, 1024, 1024, 1024), (1024 - d, 1024, 1024, 1024)
            la, lb = "roll (ch0+): lateral", "roll (ch0-): lateral opuesto (igual, vuelve)"
        else:
            return
        print("   (deflexion=%d, %.1fs por tramo)" % (d, secs), flush=True)
        self._fly_loop(a,       secs,  label="   " + la)
        self._fly_loop(NEUTRAL, brake, label="   centro (freno)")
        self._fly_loop(b,       secs,  label="   " + lb)
        self._fly_loop(NEUTRAL, brake, label="   centro (freno)")

    def engage(self, secs=3.0):
        """SUSCRIPCION 0x51 (EXP-025): escucha el serial del dron en el downlink y
        manda el handshake 0x51/02+06+08 que ENGANCHA al FC. Sin esto el FC ignora
        todo. Devuelve True si se envio (serial encontrado)."""
        t0 = last_ka = time.time()
        while time.time() - t0 < secs and not self.serial:
            if time.time() - last_ka >= 0.5:
                self.s.keepalive(); last_ka = time.time()   # no dejar enfriar la sesion
            self.s.sock.settimeout(0.15)
            try:
                d, a = self.s.sock.recvfrom(65535)
            except (socket.timeout, BlockingIOError):
                continue
            if a[0] == N.DRONE[0]:
                self.serial = N.find_drone_serial(d)
        if not self.serial:
            return False
        self._wrapped(N.sub02_frame())
        self._wrapped(N.sub06_frame(self.serial))
        self._wrapped(N.sub08_frame(self.serial))
        return True

    def sub13(self):
        """Un frame del stream de suscripcion 0x51/0x13 (mantiene el enganche)."""
        self.sub_ctr = (self.sub_ctr + 1) & 0xff
        return self._wrapped(N.sub13_frame(self.sub_ctr))

    def read_osd(self, secs=2.5):
        """Lee el OSD del FC (estado + motivo no-arranque) manteniendo el enganche.
        Devuelve dict o None. None => el FC NO nos esta enviando OSD = NO enganchado."""
        t0 = last_sub = last_stk = time.time(); osd = None
        while time.time() - t0 < secs:
            now = time.time()
            if self.serial and now - last_sub >= 0.2:
                self.sub13(); last_sub = now
            if now - last_stk >= 0.05:                    # sticks NEUTRO vivos (~20Hz)
                self.stick(*NEUTRAL); last_stk = now
            self.s.sock.settimeout(0.1)
            try:
                d, a = self.s.sock.recvfrom(65535)
            except (socket.timeout, BlockingIOError):
                continue
            if a[0] == N.DRONE[0]:
                r = N.find_osd_general(d)
                if r: osd = r
                b = N.find_battery_dynamic(d)
                if b: self.last_batt = b
        return osd

    def report_fc(self, osd):
        """Imprime el estado real del FC. Devuelve True si esta enganchado (hay OSD)."""
        if not osd:
            print(">>> OSD del FC: NO recibido -> el FC NO esta enganchado (no nos procesa).", flush=True)
            return False
        st = N.FLYC_STATE_ENUM.get(osd["flyc_state"], "0x%02x?" % osd["flyc_state"])
        why = N.START_FAIL_ENUM.get(osd["start_fail_reason"], "0x%02x (?)" % osd["start_fail_reason"])
        print(">>> OSD del FC (enganchado): estado=%s  en_tierra=%s  motores=%s  gps=%s"
              % (st, osd["on_ground"], osd["motor_on"], osd["gps_used"]), flush=True)
        print("    TELEMETRIA: %s" % fmt_telem(osd, self.last_batt), flush=True)
        print("    MOTIVO NO-ARRANQUE: %s (happened=%s)" % (why, osd["start_fail_happened"]), flush=True)
        return True

    def set_mode(self, mode=N.MODE_MANUAL):
        return self._wrapped(N.mode_frame(self._dseq(), mode))

    def detection_prep(self):
        """Housekeeping del arranque que la app manda antes del despegue (params +
        GETs + Detection). EXP-024: NO es takeoff ni se ha probado que sea precondicion
        obligatoria; opcional (--detection-prep). 0xda:05 va bare (como la app)."""
        self._wrapped(N.f8_frame(self._dseq()))
        self._wrapped(N.get_plane_name_frame(self._dseq()))
        self._wrapped(N.get_fs_action_frame(self._dseq()))
        self._wrapped(N.frame_0d03(self._dseq()))
        self.s.send_command(N.detection_setswitch_frame(self._dseq()))   # bare
        self._wrapped(N.detection_frame_0a(self._dseq()))
        n = datetime.now()
        self._wrapped(N.detection_frame_07(self._dseq(), n.year, n.month, n.day,
                                           n.hour, n.minute, n.second))
        self._wrapped(N.detection_frame_08(self._dseq()))

    def heartbeat(self):
        """0x03/0xd7 GetPushFlightRecord (suscripcion, housekeeping). Opcional."""
        if not self.hb_started:
            self.hb_started = True
            return self._wrapped(N.d7_frame(self._dseq(), 0, init=True))
        r = self._wrapped(N.d7_frame(self._dseq(), self.hb))
        self.hb = (self.hb + 1) & 0xffffffff
        return r

    # -- CONTROL DE LA CAMARA (gimbal, EXP-029) ------------------------------------
    def gimbal_rate(self, v_pitch, wrapped=True):
        """Comanda VELOCIDAD de inclinacion de la camara (0x04/0x01). v_pitch: 1024=quieta,
        <1024=abajo, >1024=arriba (mas lejos del centro = mas rapido). Un frame; para mover
        de verdad hay que mandarlo en stream ~10Hz (lo hacen point_camera / tilt_camera)."""
        fr = N.gimbal_control_frame(self._dseq(), int(v_pitch))
        return self._wrapped(fr) if wrapped else self.s.send_command(fr)

    def read_gimbal(self, secs=0.6):
        """Lee el angulo actual de la camara (gpitch) del Push Position, manteniendo el
        enganche. Devuelve grados (0=frente, neg=abajo) o None."""
        t0 = last_sub = last_ka = time.time(); p = None
        while time.time() - t0 < secs:
            now = time.time()
            if self.serial and now - last_sub >= 0.2: self.sub13(); last_sub = now
            if now - last_ka >= 0.5: self.s.keepalive(); last_ka = now
            self.s.sock.settimeout(0.1)
            try:
                d, a = self.s.sock.recvfrom(65535)
            except (socket.timeout, BlockingIOError):
                continue
            if a[0] == N.DRONE[0]:
                g = N.find_gimbal_position(d)
                if g: p = g["gpitch"]
        return p

    def point_camera(self, target_deg, tol=1.5, timeout=6.0, kp=40, vmax=400, vmin=130):
        """Apunta la camara a 'target_deg' (0=frente, negativo=abajo, positivo=arriba) en
        LAZO CERRADO: usa el feedback del Push Position para mandar rate arriba/abajo,
        proporcional al error (frena al acercarse), y HOLD al llegar. Devuelve el angulo
        final. Sirve tanto en tierra como en vuelo (no toca los motores)."""
        t0 = last_send = last_sub = last_ka = time.time()
        cur = None
        while time.time() - t0 < timeout:
            now = time.time()
            self.s.sock.settimeout(0.04)
            try:
                d, a = self.s.sock.recvfrom(65535)
                if a[0] == N.DRONE[0]:
                    g = N.find_gimbal_position(d)
                    if g: cur = g["gpitch"]
            except (socket.timeout, BlockingIOError):
                pass
            if self.serial and now - last_sub >= 0.2: self.sub13(); last_sub = now
            if now - last_ka >= 0.5: self.s.keepalive(); last_ka = now
            if now - last_send >= 0.1:
                if cur is None:
                    self.gimbal_rate(1024)                    # sin lectura aun: no mover
                else:
                    err = target_deg - cur                    # >0 => subir, <0 => bajar
                    if abs(err) <= tol:
                        self.gimbal_rate(1024); return cur     # llegado: HOLD y fin
                    mag = min(vmax, max(vmin, abs(err) * kp))
                    self.gimbal_rate(1024 + (mag if err > 0 else -mag))
                last_send = now
        return cur

    def stream(self, secs, sticks=None, mode=False, auth=True, hb=False, sub=True, label=""):
        """Streamea durante 'secs' varias 'pistas' a su frecuencia observada:
             suscripcion 0x51/13 5Hz · sticks 20Hz · modo 10Hz · d7 10Hz · autoridad 1Hz.
           sub=True (por defecto) mantiene el ENGANCHE (0x51/13) si ya se hizo engage().
           Devuelve la ultima ventana RX type-5 del dron."""
        if label: print(label, flush=True)
        end = time.time() + secs
        nt = {"stick": 0.0, "mode": 0.0, "hb": 0.0, "auth": 0.0, "ka": 0.0, "sub": 0.0}
        last_win = None
        while time.time() < end:
            now = time.time()
            if sub and self.serial and now >= nt["sub"]:
                self.sub13(); nt["sub"] = now + 0.2         # ~5 Hz, mantiene el enganche
            if mode and now >= nt["mode"]:
                self.set_mode(); nt["mode"] = now + 0.1
            if hb and now >= nt["hb"]:
                self.heartbeat(); nt["hb"] = now + 0.1
            if sticks and now >= nt["stick"]:
                self.stick(*sticks); nt["stick"] = now + 0.05
            if auth and now >= nt["auth"]:
                self.authority(); nt["auth"] = now + 1.0
            if now >= nt["ka"]:
                self.s.keepalive(); nt["ka"] = now + 0.5
            w = self.s.poll(0.01)
            if w: last_win = w
        return last_win


def run_common(f, args):
    """HELLO ya hecho. init + SUSCRIPCION 0x51 (engancha al FC) + modo + settle NEUTRO.
       Detection prep solo si --detection-prep (EXP-024: no probado como precondicion).
       Comun a DRY y a --fly. NO incluye el despegue (AUTO_FLY)."""
    print("enviando init (%d frames)..." % len(INIT))
    for fr in INIT:
        f.s.send_command(fr); time.sleep(0.03)
    ok = f.engage()
    print(">>> ENGANCHE 0x51: %s" % ("OK (serial en vivo, FC deberia procesarnos)"
                                     if ok else "FALLO (no llego el serial del dron)"), flush=True)
    f.stream(1.5, mode=True, auth=True, label="0) fijando MODO MANUAL + autoridad + suscripcion...")
    f.stream(args.settle, NEUTRAL, mode=True,
             label="1) settle: modo Manual + NEUTRO + autoridad var-0%d + suscripcion" % f.auth_state)
    if getattr(args, "detection_prep", False):
        print("2) Detection prep (0x03/0xf8 + GETs + 0x03/0xda). Opcional; NO despega.", flush=True)
        f.detection_prep()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fly", action="store_true", help="ejecutar VUELO REAL (motores)")
    ap.add_argument("--armed-ok", dest="armed_ok", action="store_true",
                    help="2do candado: confirma exterior+supervisado+failsafe")
    ap.add_argument("--lat", type=float, default=None, help="latitud grados (autoridad var-03)")
    ap.add_argument("--lon", type=float, default=None, help="longitud grados (autoridad var-03)")
    ap.add_argument("--settle", type=float, default=4.0)
    ap.add_argument("--hover", type=float, default=4.0)
    ap.add_argument("--land", type=float, default=12.0)
    ap.add_argument("--land-mode", dest="land_mode", choices=("throttle", "auto"),
                    default="throttle",
                    help="throttle: descenso por throttle-min (EXP-027, por defecto); "
                         "auto: AUTO_LANDING 0x03/0x2a:02 (no baja al Neo, solo comparacion)")
    ap.add_argument("--maneuver", choices=("none", "yaw", "forward", "roll", "demo"), default="none",
                    help="movimiento direccional tras el hover (EXP-028). yaw=giro, forward=cabeceo, "
                         "roll=alabeo (van y vuelven); demo=secuencia izq/der/frente/atras/giro-der/giro-izq. "
                         "none=solo sube/baja")
    ap.add_argument("--move-secs", dest="move_secs", type=float, default=2.0,
                    help="duracion de CADA tramo de la maniobra (ida = vuelta, para volver al "
                         "inicio). OJO: en forward/roll mas segundos = mas distancia recorrida")
    ap.add_argument("--defl", type=float, default=None,
                    help="magnitud del stick sobre el centro (1024) para la maniobra. Default "
                         "por eje (~150-180). Subir (p.ej 300-400) para vencer el hold de "
                         "posicion por vision en forward/roll. Tope 500")
    ap.add_argument("--detection-prep", dest="detection_prep", action="store_true",
                    help="enviar el housekeeping Detection/params antes del despegue (opcional)")
    args = ap.parse_args()

    real = args.fly and args.armed_ok
    if args.fly and not args.armed_ok:
        print("!! --fly requiere tambien --armed-ok (confirmacion de seguridad). Abortado.")
        sys.exit(1)

    s = N.Type5Session()
    print("=" * 64)
    print("  flight.py  —  %s" % ("VUELO REAL (motores)" if real else "DRY RUN (sin despegue)"))
    print("  seed=0x%04x primer seq=0x%04x session=0x%04x" % (s.seed, s.seq, s.session))
    if args.lat is None or args.lon is None:
        print("  autoridad en VAR-02 (coord en cero). GPS NO es requisito (EXP-024); el Neo")
        print("  vuela por vision/IR. --lat/--lon (VAR-03) es opcional, no cambia el armado.")
    else:
        print("  autoridad VAR-03 con coordenada provista (no se registra el valor).")
    print("=" * 64)
    if not s.open():
        print("SIN ack -> revisa WiFi del Neo / DJI Fly cerrado."); sys.exit(1)
    print("hello -> ACK. Sesion abierta.")

    base = None
    for _ in range(10):
        w = s.poll(0.1)
        if w: base = w; break
    print("ventana RX type-5 baseline:", "0x%04x" % base[0] if base else "?")

    f = Flight(s, args.lat, args.lon)

    if not real:
        run_common(f, args)
        win = f.stream(args.hover, NEUTRAL, mode=True,
                       label="3) DRY: modo + NEUTRO + autoridad (NO manda AUTO_FLY)...")
        print("ventana RX final:", "0x%04x" % win[0] if win else "?")
        # verdad del terreno: ¿el FC nos engancho? ¿que reporta?
        f.report_fc(f.read_osd(2.5))
        s.sock.close(); return

    # ---- VUELO REAL ----
    print("\n" + "!" * 64)
    print(" VUELO REAL. Area despejada (sin personas) + piso normal (sensor IR) + supervisado.")
    print(" Ctrl+C = ATERRIZAR (throttle-min). Corte real = BOTON del dron.")
    print("!" * 64, flush=True)
    try:
        run_common(f, args)
        # Confirmacion tecleada: AUTO_FLY despega de verdad. Freno anti-despegue-interior.
        # El prompt y la cuenta van dentro de KeepAlive para que la sesion NO muera en la
        # pausa (si no, la ventana RX se congela y el despegue se ignora).
        print("\n  El siguiente paso manda AUTO_FLY (0x03/0x2a:01): PUEDE despegar.")
        print("  Confirma: area despejada (sin personas), dron plano en piso normal (sensor IR).")
        with KeepAlive(s):
            try:
                confirmed = input("  Escribe VOLAR y Enter para despegar (cualquier otra cosa aborta): ").strip()
            except EOFError:
                confirmed = ""
            if confirmed != "VOLAR":
                print(">>> No confirmado / stdin no interactivo. Abortado sin despegar.")
                s.sock.close(); return
            print(">>> DESPEGUE en 5 s (Ctrl+C aborta)...", flush=True)
            for i in range(5, 0, -1):
                print("   ", i, flush=True); time.sleep(1.0)
        # re-sincroniza y LEE el estado real del FC justo antes de armar
        rw = f.stream(1.0, NEUTRAL, mode=True, label="4) re-sync de sesion antes de AUTO_FLY...")
        print("   ventana RX pre-AUTO_FLY:", ("0x%04x" % rw[0]) if rw else "?", flush=True)
        f.report_fc(f.read_osd(2.0))
        print("5) AUTO_FLY (FunctionControl 0x03/0x2a:01, envuelto)...", flush=True)
        f.auto_fly()
        wtk = f.stream(args.hover, NEUTRAL, mode=True,
                       label="5) HOVER: NEUTRO (modo Manual) + autoridad")
        print("   ventana RX t5:", ("0x%04x" % wtk[0]) if wtk else "?",
              "(seq propio ~0x%04x)" % f.s.seq, flush=True)
        if args.maneuver != "none":
            print("5b) MANIOBRA '%s' (conservadora; observa el dron y la telemetria)..."
                  % args.maneuver, flush=True)
            f.maneuver(args.maneuver, args.move_secs, defl=args.defl)
            f._fly_loop(NEUTRAL, 1.5, label="5c) re-estabilizando en hover antes de aterrizar...")
        if args.land_mode == "auto":
            print("6) AUTO_LANDING (0x03/0x2a:02, envuelto). Mira descender...", flush=True)
            f.auto_landing()
            f.stream(args.land, NEUTRAL, mode=True, label="")
        else:
            print("6) ATERRIZAJE por throttle-min (ch2 al minimo). Mira descender...", flush=True)
            landed = f.descend(args.land)
            print(">>> " + ("touchdown CONFIRMADO (motores apagados tras aterrizar)."
                            if landed else
                            "fin de la ventana de descenso SIN confirmacion (motores no se apagaron) -> revisa el dron."),
                  flush=True)
        print(">>> Fin. Si sigue en el aire: palm-land, BOTON del dron o failsafe.", flush=True)
    except KeyboardInterrupt:
        print("\n!! ABORTO -> ATERRIZAJE por throttle-min (descend)", flush=True)
        try:
            f.descend(args.land)
        except KeyboardInterrupt:
            print("Saliendo. Failsafe=Aterrizar / palm-land / BOTON del dron.")
    finally:
        s.sock.close()
    print("FIN del vuelo.")

if __name__ == "__main__":
    main()
