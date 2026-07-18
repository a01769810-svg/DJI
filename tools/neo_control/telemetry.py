#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
telemetry.py — Telemetria EN VIVO del DJI Neo, SIN despegar (EXP-028). SEGURO EN SUELO.

Conecta, ENGANCHA la sesion (suscripcion 0x51, igual que flight.py) y se queda
escuchando el downlink del FC para decodificar y mostrar:
  - BATERIA: % restante (OSD General) y, si el dron lo empuja, voltaje/corriente/
    temperatura/celdas (Battery Dynamic Data 0x0d/0x02).
  - SENSORES/ESTADO: altura, altura ultrasonica, velocidad (vgx/vgy/vgz), actitud
    (pitch/roll/yaw), satelites GPS, flags (usonic, MVO, gps_used, req_land...).
  - CENSO: cuenta TODOS los (snd,set,id) que llegan del dron, para descubrir mensajes
    de telemetria que aun no decodificamos (bateria dedicada, IMU, vision, etc.).

NO manda AUTO_FLY ni arma nada: solo suscripcion + sticks NEUTRO (inocuos con motores
apagados) para mantener el enganche, igual que el DRY run de flight.py. No despega.

USO (via neo.ps1, que conecta al WiFi del Neo):
  .\\neo.ps1 telemetry.py                 # 30 s de telemetria en vivo + censo final
  .\\neo.ps1 telemetry.py --secs 60        # mas tiempo
  .\\neo.ps1 telemetry.py --census         # imprime el censo completo al terminar
"""
import argparse, socket, time, collections
import neo_udp as N
import flight as F


def fmt_osd(o):
    """Linea compacta de telemetria del OSD General. OJO: batt_remain del OSD del Neo es
    basura (contador, no %); la bateria buena va en la linea BATT (Battery Dynamic Data)."""
    sats = o.get("gps_nums", "?")
    st = N.FLYC_STATE_ENUM.get(o["flyc_state"], "0x%02x?" % o["flyc_state"])
    return ("alt=%.1fm  vel=(%.1f,%.1f,%.1f)m/s  act=(p%.0f r%.0f y%.0f)  "
            "sats=%s  estado=%s tierra=%s motor=%s usonic=%s mvo=%s"
            % (o["height_m"], o["vgx"], o["vgy"], o["vgz"],
               o["pitch"], o["roll"], o["yaw"], sats, st,
               o["on_ground"], o["motor_on"], o["usonic_on"], o["mvo_used"]))


def fmt_batt(b):
    """Linea de Battery Dynamic Data si el dron lo empuja."""
    return ("V=%.2fV  I=%dmA  soc=%d%%  cap=%d/%d mAh  celdas=%d  temp_raw=%d"
            % (b["voltage_mv"] / 1000.0, b["current_ma"], b["soc"],
               b["remain_mah"], b["full_mah"], b["cells"], b["temp_raw"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--secs", type=float, default=30.0, help="duracion de la escucha")
    ap.add_argument("--census", action="store_true",
                    help="imprime el censo completo de (snd,set,id) del dron al terminar")
    args = ap.parse_args()

    s = N.Type5Session()
    print("=" * 64)
    print("  telemetry.py  —  TELEMETRIA EN VIVO (sin despegar, SEGURO en suelo)")
    print("  seed=0x%04x session=0x%04x  escucha=%.0fs" % (s.seed, s.session, args.secs))
    print("=" * 64)
    if not s.open():
        print("SIN ack -> revisa WiFi del Neo / DJI Fly cerrado."); return
    print("hello -> ACK. Sesion abierta.")

    f = F.Flight(s)
    print("enviando init (%d frames)..." % len(F.INIT))
    for fr in F.INIT:
        s.send_command(fr); time.sleep(0.03)
    ok = f.engage()
    print(">>> ENGANCHE 0x51: %s" % ("OK (el FC deberia empujar telemetria)"
                                     if ok else "FALLO (no llego el serial del dron)"), flush=True)

    census = collections.Counter()
    osd = batt = gimb = None
    got_osd = got_batt = got_gimb = False
    pos = N.PositionEstimator()          # (x,y,z) local por dead-reckoning de vgx/vgy (MVO)
    t0 = time.time()
    nt = {"stick": 0.0, "sub": 0.0, "ka": 0.0, "print": 0.0}
    print("--- telemetria (Ctrl+C para salir) ---", flush=True)
    try:
        while time.time() - t0 < args.secs:
            now = time.time()
            if f.serial and now >= nt["sub"]:
                f.sub13(); nt["sub"] = now + 0.2                 # mantiene el enganche
            if now >= nt["stick"]:
                f.stick(*F.NEUTRAL); nt["stick"] = now + 0.05    # NEUTRO inocuo (motores off)
            if now >= nt["ka"]:
                s.keepalive(); nt["ka"] = now + 0.5
            s.sock.settimeout(0.1)
            try:
                d, a = s.sock.recvfrom(65535)
            except (socket.timeout, BlockingIOError):
                d = None
            if d and a[0] == N.DRONE[0]:
                for snd, cset, cid, pl in N.scan_duml(d):
                    census[(snd, cset, cid)] += 1
                o = N.find_osd_general(d)
                if o:
                    osd = o; got_osd = True
                    pos.update(o, now)          # integra la velocidad -> posicion local
                b = N.find_battery_dynamic(d)
                if b: batt = b; got_batt = True
                g = N.find_gimbal_position(d)
                if g: gimb = g; got_gimb = True
            if now >= nt["print"]:
                nt["print"] = now + 0.5
                if osd:
                    print("  t+%5.1f  %s" % (now - t0, fmt_osd(osd)), flush=True)
                    print("           POS(dead-reckoning MVO) x=%+.2f y=%+.2f z=%.2f m  (camino %.2fm, DERIVA)"
                          % (pos.x, pos.y, pos.z, pos.dist), flush=True)
                if batt:
                    print("           BATT  %s" % fmt_batt(batt), flush=True)
                if gimb:
                    print("           CAMARA pitch=%.1f (abajo<0<arriba) roll=%.1f yaw=%.1f"
                          % (gimb["gpitch"], gimb["groll"], gimb["gyaw"]), flush=True)
                if not osd:
                    print("  t+%5.1f  (sin OSD todavia; el FC aun no empuja telemetria)"
                          % (now - t0), flush=True)
    except KeyboardInterrupt:
        print("\n(interrumpido)")
    finally:
        s.sock.close()

    print("\n" + "=" * 64)
    print("RESUMEN")
    print("  OSD General (0x03/0x43): %s" % ("SI llega" if got_osd else "NO llego"))
    print("  Battery Dynamic (0x0d/0x02): %s" % ("SI llega" if got_batt else "NO llego"))
    print("  Gimbal Position (0x04/0x05): %s" % ("SI llega" if got_gimb else "NO llego"))
    if osd:
        print("  ultimo: %s" % fmt_osd(osd))
    if batt:
        print("  bateria: %s" % fmt_batt(batt))
    if gimb:
        print("  camara: pitch=%.1f roll=%.1f yaw=%.1f" % (gimb["gpitch"], gimb["groll"], gimb["gyaw"]))
    if args.census or not got_batt:
        print("\n-- CENSO de mensajes del dron (snd/set/id : n) --")
        for (snd, cset, cid), n in sorted(census.items(), key=lambda x: -x[1]):
            print("   snd=0x%02x set=0x%02x id=0x%02x : %d" % (snd, cset, cid, n))
        print("  (busca sets no decodificados: 0x0d bateria, 0x0a vision, 0x04 gimbal...)")


if __name__ == "__main__":
    main()
