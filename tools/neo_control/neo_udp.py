#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
neo_udp.py — Constructor CORRECTO del protocolo UDP propietario del DJI Neo.

Reemplaza la interpretacion vieja del "wrapper" (EXP-001..017), que era
INCORRECTA. Basado en samuelsadok/dji_protocol (udp_protocol.md) y VALIDADO
byte-a-byte contra el trafico real de la app (Quinta prueba.pcap): 8/8 paquetes
type-5 reconstruidos identicos.

Cabecera comun (8 bytes) — offsets dentro del payload UDP:
  0x00-01  longitud (bits 14:0) | bit15=1   (= len del payload UDP)
  0x02-03  session id
  0x04-05  numero de secuencia (!=0 solo en tipos 0x02/0x03/0x05)
  0x06     tipo de paquete (0x00 hello .. 0x06)
  0x07     XOR de los bytes 0..6            <-- ANTES poniamos un contador (BUG)

Type-5 (comandos app->dron), campos de flow-control tras la cabecera:
  0x08-09  type5 send window start   (mayor seq ya NO cacheado; sube con los ACK del dron)
  0x0a-0b  type5 send window end     (= seq de este paquete; mayor seq cacheado)
  0x0c-0d  resend state 1 (0 si no hay retransmision)
  0x0e-0f  resend state 2 (0)
  0x10     contador de paquetes type-5 (1,2,3,...)
  0x11-13  01 00 00
  0x14+    payload DJI MB (0x55...)

Reglas de secuencia (VALIDADAS en Quinta):
  - El HELLO lleva en 0x08-09 el "seed" (lower 3 bits = 0).
  - El primer type-5 usa seq = seed + 8, y AVANZA de +8 en +8.
  - El dron inicializa su ventana RX type-5 en 'seed' y la avanza al aceptar
    nuestros comandos: se OBSERVA en sus paquetes type-1, offset 0x18-0x1b.

SEGURIDAD: este modulo solo CONSTRUYE/PARSEA bytes. No despega, no arma, no
mueve motores. El comando de vuelo debe darlo un script gated aparte.
"""
import socket, struct, time

# --- CRC del DJI MB / DUML (validados contra frames reales del Neo) ---
def _tab(poly):
    t = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ poly if c & 1 else c >> 1
        t.append(c)
    return t
_T8, _T16 = _tab(0x8c), _tab(0x8408)
def mb_crc8(d, c=0x77):
    for b in d: c = _T8[(b ^ c) & 0xff]
    return c
def mb_crc16(d, v=0x3692):
    for b in d: v = (v >> 8) ^ _T16[(b ^ v) & 0xff]
    return v & 0xffff

DRONE = ("192.168.2.1", 9003)

# HELLO capturado de la app (type-0). offset 8-9 = seed = 0x7268 (lower 3 bits 0).
HELLO = bytes.fromhex(
    "30804d6e00000093687264006400c005140000640000019001c005140000640014006400c00514000064000101040102")

def hello_seed(hello=HELLO):
    """Seed que siembra el seq de los streams type-2/type-5."""
    return hello[8] | (hello[9] << 8)

def hello_session(hello=HELLO):
    return hello[2] | (hello[3] << 8)


def header(length, session, seq, ptype):
    """8 bytes de cabecera comun con XOR correcto en 0x07."""
    h = bytearray(8)
    h[0] = length & 0xff
    h[1] = 0x80 | ((length >> 8) & 0x7f)
    h[2] = session & 0xff
    h[3] = (session >> 8) & 0xff
    h[4] = seq & 0xff
    h[5] = (seq >> 8) & 0xff
    h[6] = ptype & 0xff
    x = 0
    for b in h[:7]:
        x ^= b
    h[7] = x
    return h


def build_type5(session, seq, send_start, send_end, ctr, mb):
    """Paquete type-5 (comando) con cabecera + flow-control correctos."""
    length = 0x14 + len(mb)
    h = header(length, session, seq, 0x05)
    fc = bytearray(0x14 - 8)               # 0x08..0x13
    fc[0] = send_start & 0xff; fc[1] = (send_start >> 8) & 0xff
    fc[2] = send_end & 0xff;   fc[3] = (send_end >> 8) & 0xff
    # 0x0c..0x0f resend states = 0
    fc[8] = ctr & 0xff                     # 0x10
    fc[9] = 0x01                           # 0x11
    # 0x12,0x13 = 0
    return bytes(h) + bytes(fc) + mb


def mb_frame(sender, receiver, dseq, attr, cmd_set, cmd_id, payload=b""):
    """Construye un frame DJI MB/DUML con CRC-8 de cabecera y CRC-16 final."""
    body = bytearray()
    body += b"\x55"
    ln = 13 + len(payload)                 # total: 55 len ver crc8 snd rcv seq(2) attr set id pl crc16(2)
    body.append(ln & 0xff)
    body.append(0x04 | ((ln >> 8) & 0x03))          # byte2: version(0x04) | bits altos de len
    body.append(mb_crc8(bytes(body[:3])))
    body += bytes([sender & 0xff, receiver & 0xff])
    body += struct.pack("<H", dseq & 0xffff)
    body += bytes([attr & 0xff, cmd_set & 0xff, cmd_id & 0xff])
    body += payload
    body += struct.pack("<H", mb_crc16(bytes(body)))
    return bytes(body)


# --- Comando de MODO DE VUELO (EXP-016), inocuo: solo fija el modo, NO vuela ---
# 878867a3 = constante del dron; penultimo byte del payload = modo. 09 = MANUAL.
MODE_MANUAL = 0x09
# Frame MB de modo MANUAL capturado VERBATIM de la app (CRCs validos, DUML seq 0xd2e4).
MODE_MANUAL_FRAME = bytes.fromhex("551504a90217e4d24003f9878867a3090000003d10")
def mode_payload(mode):
    return bytes.fromhex("878867a3") + bytes([mode, 0x00, 0x00, 0x00])

def mode_frame(dseq, mode=MODE_MANUAL):
    # sender 0x02 (app), receiver 0x17, attr 0x40, cmd_set 0x03, cmd_id 0xf9
    return mb_frame(0x02, 0x17, dseq, 0x40, 0x03, 0xf9, mode_payload(mode))


# ---------------------------------------------------------------------------
# Builders de vuelo. VALIDADOS byte a byte contra Quinta/Octava por
# analysis/validate_arm.py. Nombres de comando confirmados contra el mapa
# historico DJI P3 (ctomichael/fpv_live) y cruzados con nuestras capturas.
# ---------------------------------------------------------------------------

# ============================ DESPEGUE / ATERRIZAJE REAL ====================
# EXP-024: el despegue del Neo es FunctionControl 0x03/0x2a, NO 0x03/0xda.
#   Confirmado en nuestras capturas: 0x03/0x2a:01 (AUTO_FLY) aparece SOLO en las 4
#   sesiones con vuelo real (Quinta/Octava/Cuarta/Tercer), nunca en las de tierra;
#   el dron responde DN 0x03/0x2a payload=00 (ack). AUTO_LANDING=02 al aterrizar.
#   VA ENVUELTO en 0x51/0x01 (wrap x1, rcv=0x03).
AUTO_FLY = 0x01
AUTO_LANDING = 0x02
def funcctrl_frame(dseq, action):
    """0x03/0x2a FunctionControl. payload = <action:1>. snd=0x02 rcv=0x03 attr=0x40.
    01=AUTO_FLY (DESPEGUE real), 02=AUTO_LANDING (aterrizaje). Enviar ENVUELTO."""
    return mb_frame(0x02, 0x03, dseq, 0x40, 0x03, 0x2a, bytes([action & 0xff]))


# ============================ SendGpsToFlyc (autoridad/posicion) ============
def authority_frame(dseq, ts, state=0x02, lat_e6=0, lon_e6=0):
    """0x03/0x20 SendGpsToFlyc (nombre historico P3, confirmado por estructura).
      payload = <flag:1> <lat:int32 LE ×1e6> <lon:int32 LE ×1e6> <ts:uint32 LE>
      flag=0x02: lat/lon en CERO (sin referencia). flag=0x03: coordenada real (EXP-020).
      ts = timestamp Unix en segundos (Quinta/Octava decodifican a 2026).
    PRIVACIDAD: lat_e6/lon_e6 nunca se hardcodean ni se registran; se pasan en runtime."""
    if state == 0x02:
        lat_e6 = lon_e6 = 0
    body = (bytes([state & 0xff]) + struct.pack("<ii", lat_e6, lon_e6)
            + struct.pack("<I", ts & 0xffffffff))
    return mb_frame(0x02, 0x03, dseq, 0x40, 0x03, 0x20, body)


# ============================ GET / housekeeping (NO arman) =================
# EXP-024: estos NO son parte del armado; son consultas/suscripciones del arranque.
# Se conservan porque la app los manda, pero NO se asume que sean precondicion.

def d7_frame(dseq, counter, init=False):
    """0x03/0xd7 GetPushFlightRecord (nombre historico P3). Suscripcion/heartbeat de
    registro de vuelo; la app lo manda continuo. NO es control de vuelo.
      init=True: payload = 01 01 00 00 ; resto: 01 04 00 00 + <counter:uint32 LE>. attr=0x80."""
    body = b"\x01\x01\x00\x00" if init else b"\x01\x04\x00\x00" + struct.pack("<I", counter & 0xffffffff)
    return mb_frame(0x02, 0x03, dseq, 0x80, 0x03, 0xd7, body)

# 0x03/0xf8 GetParamsByHash (historico P3): lote de IDs de parametro, NO cripto (EXP-020).
F8_FIRST_BATCH = bytes.fromhex("0b163bde0b163bdf0b163be0")
def f8_frame(dseq, batch=F8_FIRST_BATCH):
    return mb_frame(0x02, 0x03, dseq, 0x40, 0x03, 0xf8, batch)

def get_plane_name_frame(dseq):
    """0x03/0x34 GetPlaneName (historico P3): consulta, payload vacio. rcv=0x03."""
    return mb_frame(0x02, 0x03, dseq, 0x40, 0x03, 0x34, b"")

def get_fs_action_frame(dseq):
    """0x03/0x3c GetFsAction (historico P3): consulta de accion failsafe, payload vacio."""
    return mb_frame(0x02, 0x03, dseq, 0x40, 0x03, 0x3c, b"")

def frame_0d03(dseq):
    """0x0d/0x03 — payload 00000000, rcv=0x0b (otro modulo). Housekeeping del arranque."""
    return mb_frame(0x02, 0x0b, dseq, 0x40, 0x0d, 0x03, b"\x00\x00\x00\x00")


# ============================ Detection 0x03/0xda (NO es despegue) ==========
# EXP-024, CORRIGE EXP-019/021/022: 0x03/0xda es Detection (mapa historico P3), NO
# takeoff. sub 0x05 = SetSwitch + uint32 bitmask; `05ffffffff` = SetSwitch(0xffffffff).
# Prueba: aparece en Septima (cambio de modos en TIERRA, sin vuelo) y a intervalos
# fijos de ~30 s = housekeeping periodico, decorrelacionado del despegue.
# Los subcomandos 0a/07/08/0d son de Detection (proposito exacto sin confirmar), NO
# una "maquina de estados de armado". Se conservan por si el prep resulta util, pero
# NO se asume precondicion. El despegue real es funcctrl_frame(AUTO_FLY).
DETECTION_RECORD_ID = b"2075123072524943360"   # 19B ASCII, fijo en Quinta/Octava

def detection_setswitch_frame(dseq):
    """0x03/0xda:05 Detection.SetSwitch(0xffffffff). NO despega."""
    return mb_frame(0x02, 0x03, dseq, 0x40, 0x03, 0xda, b"\x05\xff\xff\xff\xff")

def detection_frame_0a(dseq):
    """0x03/0xda:0a Detection (subcomando, housekeeping). payload 0a 01."""
    return mb_frame(0x02, 0x03, dseq, 0x40, 0x03, 0xda, b"\x0a\x01")

def detection_frame_07(dseq, year, month, day, hour, minute, second):
    """0x03/0xda:07 Detection (fecha/hora + record id). Housekeeping, NO despegue."""
    body = (b"\x07" + struct.pack("<H", year)
            + bytes([month & 0xff, day & 0xff, hour & 0xff, minute & 0xff, second & 0xff])
            + bytes([len(DETECTION_RECORD_ID)]) + DETECTION_RECORD_ID)
    return mb_frame(0x02, 0x03, dseq, 0x40, 0x03, 0xda, body)

def detection_frame_08(dseq):
    """0x03/0xda:08 Detection (subcomando). NO es 'commit de despegue'."""
    return mb_frame(0x02, 0x03, dseq, 0x40, 0x03, 0xda, b"\x08")

DETECTION_0D_TAIL = bytes.fromhex("9f010000931d4400f111f5fe")
def detection_stream_0d(dseq, ts32, tail=DETECTION_0D_TAIL):
    """0x03/0xda:0d Detection (stream de datos, no control de vuelo). Best-effort."""
    return mb_frame(0x02, 0x03, dseq, 0x40, 0x03, 0xda,
                    b"\x0d" + struct.pack("<I", ts32 & 0xffffffff) + tail)


# ---------------------------------------------------------------------------
# CONTENEDOR 0x51/0x01 "transmision transparente" (EXP-023). El FC atiende por este
# canal: el DESPEGUE real 0x03/0x2a (FunctionControl) va ENVUELTO aqui, igual que
# el modo 0x03/0xf9, params 0x03/0xf8, GETs 0x03/0x34 y 0x03/0x3c, 0x0d/0x03,
# 0x03/0xd7 y los Detection 0x03/0xda 0a/07/08/0d. Solo van BARE la autoridad
# 0x03/0x20 y el Detection.SetSwitch 0x03/0xda:05.
# Validado: reconstruye 4772/4776 (Quinta) y 2152/2156 (Octava) frames envueltos.
#   outer: snd=0x3b rcv=0xe9 attr=0x00 cmd 0x51/0x01, dseq = contador del canal.
#   payload = <frame DUML interno completo> + cola(22B).
#   cola = 00 99d4ac02 <dseq:u32 LE> ffffffff 0182 00*7
# ---------------------------------------------------------------------------
def wrap_5101(outer_dseq, inner_frame):
    tail = (b"\x00" + bytes.fromhex("99d4ac02") + struct.pack("<I", outer_dseq & 0xffffffff)
            + b"\xff\xff\xff\xff" + b"\x01\x82" + b"\x00" * 7)
    return mb_frame(0x3b, 0xe9, outer_dseq & 0xffff, 0x00, 0x51, 0x01, inner_frame + tail)


# ---------------------------------------------------------------------------
# SUSCRIPCION 0x51 (EXP-025): ENGANCHA al flight controller. Sin esto el dron
# acepta en transporte pero el FC ignora todo; con esto el FC procesa nuestros
# comandos y pushea telemetria. Frames internos snd=0xee rcv=0xe9, se ENVUELVEN
# en 0x51/0x01. El SERIAL del dron se extrae EN VIVO del downlink (no se hardcodea).
# Constantes = UUID app (2020ee4d-..., ya en INIT) + protocolo. NO es cripto.
# ---------------------------------------------------------------------------
_SUB02 = bytes.fromhex("0504040000000200020000")
_SUB06_PRE = bytes.fromhex("04020032303230656534642d366163612d343636662d0000001a")
_SUB06_SUF = bytes.fromhex("0000000000")
_SUB08_PRE = bytes.fromhex("00001a")
_SUB08_SUF = bytes.fromhex("00")
_SUB13_TPL = bytes.fromhex(
    "0504020032303230656534642d366163612d343636662d0001010100000000000001000001010102000000b0a4180000008b2454000000")
_SUB13_CTR_OFF = 39

def sub_frame(cid, dseq, attr, payload):
    return mb_frame(0xee, 0xe9, dseq, attr, 0x51, cid, payload)

def sub02_frame():          return sub_frame(0x02, 0x0072, 0x40, _SUB02)
def sub06_frame(serial):    return sub_frame(0x06, 0x0074, 0x40, _SUB06_PRE + serial + _SUB06_SUF)
def sub08_frame(serial):    return sub_frame(0x08, 0x0000, 0xc0, _SUB08_PRE + serial + _SUB08_SUF)
def sub13_frame(counter):
    tpl = bytearray(_SUB13_TPL); tpl[_SUB13_CTR_OFF] = counter & 0xff
    return sub_frame(0x13, 0x0074, 0x00, bytes(tpl))

def _scan_frames(buf):
    """Genera (snd,cset,cid,payload) por cada DUML CRC-valido, recursivo en 0x51/0x01."""
    i, n = 0, len(buf)
    while i < n:
        if buf[i] != 0x55:
            i += 1; continue
        if i + 4 > n:
            break
        ln = buf[i+1] | ((buf[i+2] & 3) << 8)
        if ln < 13 or i + ln > n or mb_crc8(buf[i:i+3]) != buf[i+3]:
            i += 1; continue
        fr = buf[i:i+ln]
        payload = fr[11:ln-2]
        yield fr[4], fr[9], fr[10], payload
        if fr[9] == 0x51 and fr[10] == 0x01:
            yield from _scan_frames(payload)
        i += ln

def find_drone_serial(pkt):
    """Serial del dron (20B) desde un DN 0x51/0x08 o 0x51/0x13 (snd=0xe9), o None."""
    for snd, cset, cid, payload in _scan_frames(pkt):
        if cset == 0x51 and snd == 0xe9:
            if cid == 0x08 and len(payload) >= 23: return payload[3:23]
            if cid == 0x13 and len(payload) >= 24: return payload[4:24]
    return None


# --- OSD General 0x03/0x43: estado del FC + TELEMETRIA (EXP-025/028) ---
# Layout completo segun el dissector autoritativo (tools/dji-firmware-tools,
# flyc_osd_general_dissector). Offsets dentro del payload (tras la cabecera DUML):
#   @0  longitud (double, rad)      @8  latitud (double, rad)
#   @16 relative_height  int16 x0.1 m (altura al suelo)
#   @18/20/22 vgx/vgy/vgz int16 x0.1 m/s (velocidad respecto al suelo)
#   @24/26/28 pitch/roll/yaw int16 x0.1 grados (actitud)
#   @30 flyc_state (mask 0x7F)       @31 latest_cmd
#   @32 controller_state u32: on_ground 0x02, in_air 0x04, motor_on 0x08,
#       usonic_on 0x10, mvo_used 0x100, batt_req_land 0x400, gps_used 0x8000,
#       gps_level (0x3C0000 >>18)
#   @36 gps_nums (satelites)         @38 start_fail (reason 0x7F, happened 0x80)
#   @40 batt_remain (% restante)     @41 ultrasonic_height x0.1 m
FLYC_STATE_ENUM = {
    0x00:'Manual',0x01:'Atti',0x02:'Atti_CL',0x03:'Atti_Hover',0x04:'Hover',0x05:'GPS_Blake',
    0x06:'GPS_Atti',0x07:'GPS_CL',0x08:'GPS_HomeLock',0x09:'GPS_HotPoint',0x0a:'AssitedTakeoff',
    0x0b:'AutoTakeoff',0x0c:'AutoLanding',0x0d:'AttiLanding',0x0e:'NaviGo',0x0f:'GoHome',
    0x10:'ClickGo',0x11:'Joystick',0x1e:'FPV',0x1f:'SPORT',0x20:'NOVICE',0x21:'FORCE_LANDING',
}
START_FAIL_ENUM = {
    0x00:'None/Allow start',0x01:'Compass error',0x02:'Assistant protected',0x03:'Device lock protect',
    0x04:'Off radius limit landed',0x05:'IMU need adv-calib',0x06:'IMU SN error',0x07:'Temperature cal not ready',
    0x08:'Compass calibration in progress',0x09:'Attitude error',0x0a:'Novice mode without gps',
    0x0b:'Battery cell error',0x0c:'Battery comm error',0x0d:'Battery voltage very low',0x12:'Battery not ready',
    0x13:'May run simulator',0x14:'Gear pack mode',0x15:'Atti limit',0x16:'Product not activation',
    0x17:'In fly limit area',0x19:'ESC error',0x1a:'IMU is initing',0x1b:'System upgrade',
    0x1c:'Have run simulator, please restart',0x1d:'IMU cali in progress',0x1e:'Too large tilt on auto takeoff',
    0x29:'SN invalid',0x2d:'GPS disconnect',0x2e:'Out of whitelist area',0x43:'Aircraft Type Mismatch',
}

def decode_osd_general(pl):
    """Decodifica el payload de OSD General (0x03/0x43): estado del FC + telemetria
    (bateria, altura, velocidad, actitud, sensores). Devuelve dict o None si corto.
    Las claves de estado (flyc_state/on_ground/motor_on/...) se mantienen estables;
    las de telemetria se agregan si el payload es lo bastante largo."""
    if len(pl) < 39:
        return None
    cs = struct.unpack_from("<I", pl, 32)[0]
    d = dict(
        flyc_state=pl[30] & 0x7F,
        on_ground=bool(cs & 0x02), in_air=bool(cs & 0x04),
        motor_on=bool(cs & 0x08), usonic_on=bool(cs & 0x10),
        mvo_used=bool(cs & 0x100), batt_req_land=bool(cs & 0x400),
        gps_used=bool(cs & 0x8000), gps_level=(cs >> 18) & 0xF,
        start_fail_reason=pl[38] & 0x7F, start_fail_happened=bool(pl[38] & 0x80),
        height_m=struct.unpack_from("<h", pl, 16)[0] / 10.0,
        vgx=struct.unpack_from("<h", pl, 18)[0] / 10.0,
        vgy=struct.unpack_from("<h", pl, 20)[0] / 10.0,
        vgz=struct.unpack_from("<h", pl, 22)[0] / 10.0,
        pitch=struct.unpack_from("<h", pl, 24)[0] / 10.0,
        roll=struct.unpack_from("<h", pl, 26)[0] / 10.0,
        yaw=struct.unpack_from("<h", pl, 28)[0] / 10.0,
    )
    if len(pl) >= 37: d["gps_nums"] = pl[36]
    if len(pl) >= 41: d["batt_remain"] = pl[40]          # % restante (segun el FC)
    if len(pl) >= 42: d["ultrasonic_m"] = pl[41] / 10.0
    return d

def find_osd_general(pkt):
    """Decodifica el OSD General de un paquete UDP crudo si viene un 0x03/0x43, o None."""
    for snd, cset, cid, payload in _scan_frames(pkt):
        if cset == 0x03 and cid == 0x43:
            d = decode_osd_general(payload)
            if d: return d
    return None


class PositionEstimator:
    """Estimacion de posicion LOCAL (x,y,z) del Neo por DEAD-RECKONING: integra la velocidad
    del OSD (vgx/vgy = salida del MVO, la odometria visual del propio Neo, en marco MUNDO fijo).
    z se toma DIRECTO de la altura (mejor que integrar vgz). Origen (0,0,0) en el primer sample
    o en reset() (p.ej. al despegar).

    ⚠️ DERIVA: integra velocidad cuantizada a 0.1 m/s -> el error crece con el tiempo (metros en
    decenas de s). Es odometria de CORTO PLAZO, NO un mapa metrico (eso lo da el SLAM). Pero la
    fuente ES la posicion visual del Neo (mvo_used), no un invento. Ver la investigacion en la
    memoria neo-local-position-routes. 'dist' acumula el camino horizontal (para juzgar la deriva)."""

    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.z = 0.0
        self.dist = 0.0          # distancia horizontal recorrida (integral de |v|)
        self.t_prev = None
        self.n = 0

    def reset(self, z=0.0):
        self.x = self.y = 0.0
        self.z = z
        self.dist = 0.0
        self.t_prev = None
        self.n = 0

    def update(self, osd, t):
        """Integra un sample. osd = dict de decode_osd_general; t = time.time().
        Devuelve (x, y, z). z sale de height_m; x,y de integrar vgx/vgy."""
        if osd is None:
            return self.x, self.y, self.z
        self.z = osd.get("height_m", self.z)
        if self.t_prev is not None:
            dt = t - self.t_prev
            if 0.0 < dt < 1.0:                    # ignora huecos grandes de telemetria
                dx = osd.get("vgx", 0.0) * dt
                dy = osd.get("vgy", 0.0) * dt
                self.x += dx
                self.y += dy
                self.dist += (dx * dx + dy * dy) ** 0.5
                self.n += 1
        self.t_prev = t
        return self.x, self.y, self.z


# --- Battery Dynamic Data 0x0d/0x02: voltaje/corriente/capacidad/temperatura ---
# Layout autoritativo (dji-firmware-tools, battery_dynamic_data_dissector), forma
# comun de 30/31 bytes con 1 byte (index/result) antes del voltaje:
#   @1 voltage u32 mV · @5 current i32 mA · @9 full_cap u32 mAh
#   @13 remain u32 mAh · @17 temperature u16 · @19 cell_size · @20 state_of_charge %
def decode_battery_dynamic(pl):
    """Decodifica Battery Dynamic Data (0x0d/0x02). Devuelve dict o None si corto.
    temp: unidades sin confirmar en el Neo (probable 0.1 C); se reporta cruda."""
    if len(pl) < 21:
        return None
    return dict(
        voltage_mv=struct.unpack_from("<I", pl, 1)[0],
        current_ma=struct.unpack_from("<i", pl, 5)[0],
        full_mah=struct.unpack_from("<I", pl, 9)[0],
        remain_mah=struct.unpack_from("<I", pl, 13)[0],
        temp_raw=struct.unpack_from("<H", pl, 17)[0],
        cells=pl[19],
        soc=pl[20],
    )

def find_battery_dynamic(pkt):
    """Battery Dynamic Data (0x0d/0x02) del dron en un paquete UDP crudo, o None."""
    for snd, cset, cid, payload in _scan_frames(pkt):
        if cset == 0x0d and cid == 0x02:
            d = decode_battery_dynamic(payload)
            if d: return d
    return None

def scan_duml(pkt):
    """Publico: itera (snd, cset, cid, payload) de cada DUML CRC-valido (recursivo en
    0x51/0x01). Para censar en vivo que mensajes empuja el dron."""
    return _scan_frames(pkt)


# --- Arranque del STREAM DE VIDEO (EXP-030) ---
# El video (paquetes type-0x02 en 9003) NO fluye solo al enganchar: la app lo pide con
# comandos de CAMARA (cset 0x02, rcv=0x01, snd=0x02) ENVUELTOS en 0x51/01. Frames verbatim
# de 'Septima prueba' (sesion CON video en tierra). Se replican como el INIT. 🧪 EXP.
#   0xd8 (~2.7/s) y 0xe8 (~1.6/s): streams continuos desde el arranque.
#   0xb5 (una vez) y 0xeb (~2/s): candidatos a iniciar/mantener el stream.
CAM_D8 = bytes.fromhex("551604fc0201efc64002d801000000000000000009fb")
CAM_E8 = bytes.fromhex("550d04330201f2c64002e89f50")
CAM_B5 = bytes.fromhex("5511049202010eca4002b500000000bf4d")
CAM_EB = bytes.fromhex("551e048a0201cbc94002eb00ff0b112700000a00030008007517d10722a9")

def request_iframe_frame(dseq):
    """0x02/0xb3 Request IFrame — pide un KEYFRAME (IDR + VPS/SPS/PPS). Necesario si nos
    colgamos al stream a mitad (solo P-frames): sin keyframe no se puede decodificar.
    snd=0x02 rcv=0x01 (camara) attr=0x40, payload vacio. EXP-031."""
    return mb_frame(0x02, 0x01, dseq, 0x40, 0x02, 0xb3, b"")


# --- Gimbal Push Position 0x04/0x05: angulo de la CAMARA (EXP-029) ---
# Layout autoritativo (dji-firmware-tools, gimbal_params_dissector):
#   @0 pitch int16 x0.1 grados (0=camara al frente, NEGATIVO=abajo, POSITIVO=arriba;
#      rango del hardware ~ -90..+47), @2 roll x0.1, @4 yaw x0.1.
# Verificado contra Quinta/Octava: en reposo pitch=0.0 (camara al frente).
def decode_gimbal_position(pl):
    """Decodifica Gimbal Push Position (0x04/0x05). Devuelve dict con el angulo de la
    camara (gpitch=inclinacion arriba/abajo) o None si corto."""
    if len(pl) < 6:
        return None
    return dict(
        gpitch=struct.unpack_from("<h", pl, 0)[0] / 10.0,   # inclinacion camara (lo que importa)
        groll=struct.unpack_from("<h", pl, 2)[0] / 10.0,
        gyaw=struct.unpack_from("<h", pl, 4)[0] / 10.0,
    )

def find_gimbal_position(pkt):
    """Gimbal Push Position (0x04/0x05) del dron en un paquete UDP crudo, o None."""
    for snd, cset, cid, payload in _scan_frames(pkt):
        if cset == 0x04 and cid == 0x05:
            d = decode_gimbal_position(payload)
            if d: return d
    return None


# --- Gimbal CONTROL: candidatos EXPERIMENTALES (EXP-029) ---
# 🧪 SIN captura de la app moviendo el gimbal; formatos del dissector autoritativo.
# Se prueban en tierra (inocuos: solo inclinan la camara, NO vuelan) contra el feedback
# del Push Position 0x04/0x05. rcv=0x04 (modulo gimbal). Se envian envueltos o bare.
def gimbal_abs_angle_frame(dseq, pitch10, roll10=0, yaw10=0, flags=0x01, field7=0):
    """0x04/0x14 Gimbal Abs Angle Control. angle1/2/3 = grados*10 int16 (orden probable
    pitch,roll,yaw, como el Push Position). flags = que ejes aplicar (bit0=angle1)."""
    body = struct.pack("<hhh", int(pitch10), int(roll10), int(yaw10)) + bytes([flags & 0xff, field7 & 0xff])
    return mb_frame(0x02, 0x04, dseq, 0x40, 0x04, 0x14, body)

def gimbal_control_frame(dseq, v_pitch, v1=1024, v2=1024):
    """0x04/0x01 Gimbal Control. 3 valores uint16 en 363..1685 (tipo stick; centro 1024 =
    quieto, <1024 y >1024 = velocidad en cada sentido)."""
    body = struct.pack("<HHH", v_pitch & 0xffff, v1 & 0xffff, v2 & 0xffff)
    return mb_frame(0x02, 0x04, dseq, 0x40, 0x04, 0x01, body)

def gimbal_move_frame(dseq, pitch_step, roll_step=0, yaw_step=0):
    """0x04/0x15 Gimbal Movement. primeros 3 int8 = paso/velocidad, resto reservado
    (20 bytes total)."""
    body = struct.pack("<bbb", pitch_step, roll_step, yaw_step) + b"\x00" * 17
    return mb_frame(0x02, 0x04, dseq, 0x40, 0x04, 0x15, body)


def parse_header(p):
    if len(p) < 8: return None
    x = 0
    for b in p[:7]: x ^= b
    return dict(length=(p[0] | (p[1] << 8)) & 0x7fff,
                session=p[2] | (p[3] << 8), seq=p[4] | (p[5] << 8),
                ptype=p[6], xor_ok=(p[7] == x))

def drone_type5_recv_window(p):
    """De un paquete type-1 del dron: (start,end) de su ventana RX type-5."""
    if len(p) < 0x1c or p[6] != 0x01: return None
    return (p[0x18] | (p[0x19] << 8), p[0x1a] | (p[0x1b] << 8))


class Type5Session:
    """Gestiona una sesion de envio type-5 con secuencia y ventanas correctas."""
    def __init__(self, hello=HELLO):
        self.hello = hello
        self.session = hello_session(hello)
        self.seed = hello_seed(hello)
        self.seq = (self.seed + 8) & 0xffff     # primer type-5 = seed+8
        self.ctr = 1                            # contador 0x10 arranca en 1
        self.send_start = self.seed             # sube con los ACK del dron
        self.dseq = 0x0001                       # secuencia DUML interna
        self.sock = None
        self.drone_next = self.seed             # sig. seq que el dron espera (su ventana RX)
        self.sent = {}                          # cache seq->pkt para retransmision

    def open(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", 0)); self.sock.settimeout(0.05)
        got = False
        for _ in range(6):
            self.sock.sendto(self.hello, DRONE)
            t0 = time.time()
            while time.time() - t0 < 0.2:
                try:
                    d, a = self.sock.recvfrom(2048)
                    if a[0] == DRONE[0] and d[:2].hex() == "0980":
                        got = True
                except socket.timeout:
                    pass
            if got: break
        return got

    WINDOW = 48          # cuanto nos permitimos adelantar a la ventana RX del dron

    def _pump(self):
        """Drena downlink, actualiza la ventana RX del dron y retransmite lo atascado."""
        for _ in range(12):
            self.sock.settimeout(0.003)
            try:
                d, a = self.sock.recvfrom(4096)
            except (socket.timeout, BlockingIOError):
                break
            if a[0] != DRONE[0]:
                continue
            w = drone_type5_recv_window(d)
            if w:
                if w[0] > self.send_start:
                    self.send_start = w[0]
                self.drone_next = w[1]          # sig. seq que el dron espera
        # si el dron sigue esperando un seq que ya mandamos, retransmitelo (en orden)
        gap = (self.seq - self.drone_next) & 0xffff
        if 0 < gap <= 0x8000 and self.drone_next in self.sent:
            self.sock.sendto(self.sent[self.drone_next], DRONE)

    def send_command(self, mb):
        """Envia UN comando MB como type-5, respetando el control de flujo del dron.
        Bloquea (pace) si nos adelantamos mas de WINDOW a la ventana RX del dron, y
        retransmite los paquetes no confirmados para no atascar el stream."""
        # 1) control de flujo: no adelantarse demasiado a lo que el dron ha aceptado
        t0 = time.time()
        while ((self.seq - self.drone_next) & 0xffff) > self.WINDOW and (time.time() - t0) < 0.5:
            self._pump()
        # 2) construir, cachear y enviar
        send_end = self.seq
        pkt = build_type5(self.session, self.seq, self.send_start, send_end, self.ctr, mb)
        self.sent[self.seq] = pkt
        self.sock.sendto(pkt, DRONE)
        sent_seq = self.seq
        self.seq = (self.seq + 8) & 0xffff
        self.ctr = (self.ctr + 1) & 0xff
        # 3) podar cache viejo (deja las ultimas ~256 tramas para retransmision)
        if len(self.sent) > 256:
            for k in sorted(self.sent)[:len(self.sent) - 256]:
                del self.sent[k]
        return sent_seq

    def keepalive(self):
        self.sock.sendto(self.hello, DRONE)

    def poll(self, timeout=0.05):
        """Devuelve (start,end) de la ventana RX type-5 del dron si llega un type-1."""
        self.sock.settimeout(timeout)
        try:
            d, a = self.sock.recvfrom(4096)
        except (socket.timeout, BlockingIOError):
            return None
        if a[0] != DRONE[0]:
            return None
        w = drone_type5_recv_window(d)
        if w:
            if w[0] > self.send_start:
                self.send_start = w[0]  # avanza nuestro send_start con el ACK del dron
            self.drone_next = w[1]
        return w
