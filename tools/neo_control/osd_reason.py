#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
osd_reason.py — Lee la telemetria OSD del propio Neo y dice POR QUE no arranca los
motores. SEGURO: no manda AUTO_FLY ni mueve motores; solo consulta y escucha.

Decodifica el frame OSD General (FlyC cmd_set 0x03 / cmd_id 0x43) segun el dissector
autoritativo de dji-firmware-tools:
  offset 30  ctrl_info/flyc_state  -> flyc_state = byte & 0x7F  (estado del FC)
  offset 32  controller_state u32  -> on_ground 0x02, in_air 0x04, motor_on 0x08,
                                       gps_used 0x8000
  offset 38  start_fail            -> start_fail_reason = byte & 0x7F  (<-- EL MOTIVO)
                                       start_fail_happened = byte & 0x80
Tambien intenta GetPlaneName/GetFsAction: si el FC responde, confirma que nos procesa.
"""
import socket, time, sys, os, collections, struct
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "analysis"))
import neo_udp as N
from func_control_probe import scan_duml
from flight import INIT, KeepAlive

FLYC_STATE = {
    0x00:'Manual',0x01:'Atti',0x02:'Atti_CL',0x03:'Atti_Hover',0x04:'Hover',
    0x05:'GPS_Blake',0x06:'GPS_Atti',0x07:'GPS_CL',0x08:'GPS_HomeLock',0x09:'GPS_HotPoint',
    0x0a:'AssitedTakeoff',0x0b:'AutoTakeoff',0x0c:'AutoLanding',0x0d:'AttiLanding',
    0x0e:'NaviGo',0x0f:'GoHome',0x10:'ClickGo',0x11:'Joystick',0x1e:'FPV',0x1f:'SPORT',
    0x20:'NOVICE',0x21:'FORCE_LANDING',0x29:'ENGINE_START',
}
START_FAIL = {
    0x00:'None/Allow start',0x01:'Compass error',0x02:'Assistant protected',
    0x03:'Device lock protect',0x04:'Off radius limit landed',0x05:'IMU need adv-calib',
    0x06:'IMU SN error',0x07:'Temperature cal not ready',0x08:'Compass calibration in progress',
    0x09:'Attitude error',0x0a:'Novice mode without gps',0x0b:'Battery cell error',
    0x0c:'Battery comm error',0x0d:'Battery voltage very low',0x0e:'Battery below user low land',
    0x0f:'Battery main vol low',0x10:'Battery temp and vol low',0x11:'Battery smart low land',
    0x12:'Battery not ready',0x13:'May run simulator',0x14:'Gear pack mode',0x15:'Atti limit',
    0x16:'Product not activation',0x17:'In fly limit area',0x18:'Bias limit',0x19:'ESC error',
    0x1a:'IMU is initing',0x1b:'System upgrade',0x1c:'Have run simulator, please restart',
    0x1d:'IMU cali in progress',0x1e:'Too large tilt angle on auto takeoff',0x1f:'Gyroscope is stuck',
    0x20:'Accel is stuck',0x21:'Compass is stuck',0x22:'Pressure sensor is stuck',
    0x23:'Pressure read negative',0x24:'Compass mod huge',0x25:'Gyro bias large',0x26:'Accel bias large',
    0x27:'Compass noise large',0x28:'Pressure noise large',0x29:'SN invalid',0x2a:'Pressure slope large',
    0x2b:'Ahrs error large',0x2c:'Flash operating',0x2d:'GPS disconnect',0x2e:'Out of whitelist area',
    0x2f:'SD Card Exception',0x3d:'IMU No connection',0x43:'Aircraft Type Mismatch',
    0x44:'Found Unfinished Module',0x49:'GPS Abnormal',0x4c:'RC Need Cali',0x53:'Invalid Version',
}

def decode_osd(pl):
    """Devuelve dict con los campos clave del OSD General, o None si es corto."""
    if len(pl) < 39:
        return None
    flyc_state = pl[30] & 0x7F
    cs = struct.unpack_from("<I", pl, 32)[0]
    sf = pl[38]
    return dict(flyc_state=flyc_state,
                on_ground=bool(cs & 0x02), in_air=bool(cs & 0x04),
                motor_on=bool(cs & 0x08), gps_used=bool(cs & 0x8000),
                start_fail_reason=sf & 0x7F, start_fail_happened=bool(sf & 0x80))

def get_frame(dseq, cid):
    return N.mb_frame(0x02, 0x03, dseq, 0x40, 0x03, cid, b"")

# --- Handshake de SUSCRIPCION 0x51 (EXP-025). Frames internos snd=0xee rcv=0xe9,
#     ENVUELTOS en 0x51/0x01. Constantes = UUID/protocolo (ya en INIT); el SERIAL
#     del dron se extrae EN VIVO del downlink (no se hardcodea). ---
SUB02 = bytes.fromhex("0504040000000200020000")
SUB06_PRE = bytes.fromhex("04020032303230656534642d366163612d343636662d0000001a")
SUB06_SUF = bytes.fromhex("0000000000")
SUB08_PRE = bytes.fromhex("00001a")
SUB08_SUF = bytes.fromhex("00")
SUB13_TPL = bytes.fromhex(
    "0504020032303230656534642d366163612d343636662d0001010100000000000001000001010102000000b0a4180000008b2454000000")
SUB13_CTR_OFF = 39   # byte del contador (2,3,4,...) dentro del stream

def sub_inner(cid, dseq, attr, payload):
    return N.mb_frame(0xee, 0xe9, dseq, attr, 0x51, cid, payload)

def extract_serial(frames):
    """Serial (20B) del dron desde DN 0x51/0x08 o 0x51/0x13 (snd=0xe9)."""
    for m in frames:
        if m["cset"] == 0x51 and m["snd"] == 0xe9:
            pl = m["payload"]
            if m["cid"] == 0x08 and len(pl) >= 23: return pl[3:23]
            if m["cid"] == 0x13 and len(pl) >= 24: return pl[4:24]
    return None

def listen(s, secs):
    frames = []
    t0 = time.time()
    while time.time() - t0 < secs:
        s.sock.settimeout(0.15)
        try:
            d, a = s.sock.recvfrom(65535)
        except (socket.timeout, BlockingIOError):
            continue
        if a[0] != N.DRONE[0]:
            continue
        for m, depth in scan_duml(d):
            frames.append(m)
    return frames

def main():
    s = N.Type5Session()
    print("=" * 60)
    print("osd_reason — motivo de no-arranque segun el propio FC (sin motores)")
    if not s.open():
        print("SIN ack -> WiFi del Neo / telefono fuera."); return
    print("hello -> ACK. sesion viva.")

    frames = []
    wd = 1; dseq = 0xc000
    with KeepAlive(s):
        for fr in INIT:
            s.send_command(fr); time.sleep(0.03)

        # 1) escuchar para extraer el SERIAL del dron (del downlink 0x51)
        pre = listen(s, 2.0)
        serial = extract_serial(pre)
        print("serial del dron:", ("<extraido %dB>" % len(serial)) if serial else "NO recibido (no se pudo enganchar)")

        # 2) burst de handshake 0x51/02,06,08 (envueltos)
        if serial:
            s.send_command(N.wrap_5101(wd, sub_inner(0x02, 0x0072, 0x40, SUB02))); wd += 1
            s.send_command(N.wrap_5101(wd, sub_inner(0x06, 0x0074, 0x40, SUB06_PRE + serial + SUB06_SUF))); wd += 1
            s.send_command(N.wrap_5101(wd, sub_inner(0x08, 0x0000, 0xc0, SUB08_PRE + serial + SUB08_SUF))); wd += 1
            print("handshake 0x51/02+06+08 enviado (con serial en vivo)")

        # 3) stream de suscripcion 0x51/0x13 + GETs, mientras escucha OSD (~6 s)
        ctr = 2; t0 = time.time()
        while time.time() - t0 < 6.0:
            if serial:
                tpl = bytearray(SUB13_TPL); tpl[SUB13_CTR_OFF] = ctr & 0xff; ctr += 1
                s.send_command(N.wrap_5101(wd, sub_inner(0x13, 0x0074, 0x00, bytes(tpl)))); wd += 1
            for cid in (0x43, 0x34, 0x3c):
                s.send_command(N.wrap_5101(wd, get_frame(dseq, cid))); wd += 1; dseq += 1
            frames += listen(s, 0.25)
        frames += pre

    # censo de lo que manda el dron (snd=0x03 = del FC)
    census = collections.Counter((m["snd"], m["cset"], m["cid"]) for m in frames)
    print("\n-- telemetria recibida (snd,cset,cid : n) --")
    for (snd, cs, ci), n in sorted(census.items(), key=lambda x: -x[1])[:15]:
        org = "FC" if snd == 0x03 else ("app" if snd == 0x02 else "0x%02x" % snd)
        print(f"   {org} 0x{cs:02x}/0x{ci:02x} : {n}")

    osd = [decode_osd(m["payload"]) for m in frames
           if m["cset"] == 0x03 and m["cid"] == 0x43 and decode_osd(m["payload"])]
    resp_get = any(m["snd"] == 0x03 and m["cset"] == 0x03 and m["cid"] in (0x34, 0x3c) for m in frames)

    print("\n" + "=" * 60)
    if osd:
        o = osd[-1]
        st = FLYC_STATE.get(o["flyc_state"], "0x%02x?" % o["flyc_state"])
        why = START_FAIL.get(o["start_fail_reason"], "0x%02x (desconocido)" % o["start_fail_reason"])
        print(">>> OSD del FC LEIDO (%d frames):" % len(osd))
        print(f"    Estado del FC   : {st}")
        print(f"    En tierra={o['on_ground']}  en aire={o['in_air']}  motores={o['motor_on']}  gps_used={o['gps_used']}")
        print(f"    >>> MOTIVO NO-ARRANQUE : {why}   (fail_happened={o['start_fail_happened']})")
    else:
        print(">>> El dron NO nos envio el OSD General (0x03/0x43) en esta sesion.")
        print("    Probablemente falta el comando de SUSCRIPCION de telemetria que hace")
        print("    la app (el OSD se 'pushea' solo tras suscribirse). Siguiente: buscar")
        print("    esa suscripcion en el pcap/dissector.")
    print(f"    [FC responde a nuestros GET (0x34/0x3c): {resp_get}]  "
          f"({'nos procesa' if resp_get else 'no responde a GETs'})")
    s.sock.close()

if __name__ == "__main__":
    main()
