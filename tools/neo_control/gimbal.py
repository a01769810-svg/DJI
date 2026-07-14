#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gimbal.py — Experimento de CONTROL de la camara (gimbal) del DJI Neo (EXP-029).
SEGURO EN SUELO: NO despega, NO arma motores (nunca manda AUTO_FLY ni throttle). Solo
inclina la camara. Motores off todo el tiempo.

Como no hay captura de la app moviendo el gimbal, probamos varios COMANDOS CANDIDATOS
(del dissector autoritativo) y medimos si el angulo de la camara cambia, usando el
Push Position 0x04/0x05 como feedback:
  - 0x04/0x14 Abs Angle Control  (angulo absoluto en grados)
  - 0x04/0x01 Gimbal Control     (3 valores tipo stick 363..1685)
  - 0x04/0x15 Gimbal Movement    (paso/velocidad)
cada uno ENVUELTO en 0x51/01 (como los comandos del FC) o BARE (type-5 directo).

USO (via neo.ps1):
  .\\neo.ps1 gimbal.py                 # barre todos los candidatos y reporta cual movio
  .\\neo.ps1 gimbal.py --watch         # solo LEE el angulo de la camara (no envia nada)
"""
import argparse, socket, time
import neo_udp as N
import flight as F

MOVE_THRESH = 2.0        # grados de cambio para considerar que la camara SI se movio


def read_pitch(f, secs):
    """Escucha 'secs' el Push Position 0x04/0x05 manteniendo el enganche; devuelve el
    ultimo gpitch visto (o None). No envia comandos de gimbal."""
    t0 = last_sub = last_ka = time.time(); p = None
    while time.time() - t0 < secs:
        now = time.time()
        if f.serial and now - last_sub >= 0.2:
            f.sub13(); last_sub = now
        if now - last_ka >= 0.5:
            f.s.keepalive(); last_ka = now
        f.s.sock.settimeout(0.1)
        try:
            d, a = f.s.sock.recvfrom(65535)
        except (socket.timeout, BlockingIOError):
            continue
        if a[0] == N.DRONE[0]:
            g = N.find_gimbal_position(d)
            if g: p = g["gpitch"]
    return p


def try_candidate(f, name, frame_fn, wrapped, secs=2.0):
    """Mide pitch base, streamea el comando candidato 'secs' (10Hz) y mide el pitch final.
    Devuelve (movio, delta). Mantiene el enganche; NUNCA arma (solo frames de gimbal)."""
    base = read_pitch(f, 1.0)
    print("  [%-26s] base=%s ..." % (name, base), flush=True, end="")
    t0 = last_send = last_sub = last_ka = time.time(); last = base
    while time.time() - t0 < secs:
        now = time.time()
        if now - last_send >= 0.1:                        # 10 Hz
            fr = frame_fn(f._dseq())
            if wrapped: f._wrapped(fr)
            else: f.s.send_command(fr)
            last_send = now
        if f.serial and now - last_sub >= 0.2:
            f.sub13(); last_sub = now
        if now - last_ka >= 0.5:
            f.s.keepalive(); last_ka = now
        f.s.sock.settimeout(0.05)
        try:
            d, a = f.s.sock.recvfrom(65535)
        except (socket.timeout, BlockingIOError):
            continue
        if a[0] == N.DRONE[0]:
            g = N.find_gimbal_position(d)
            if g: last = g["gpitch"]
    delta = (last - base) if (base is not None and last is not None) else None
    moved = delta is not None and abs(delta) >= MOVE_THRESH
    print(" final=%s delta=%s  %s"
          % (last, ("%+.1f" % delta if delta is not None else "?"),
             ">>> LA CAMARA SE MOVIO <<<" if moved else "(sin cambio)"), flush=True)
    return moved, delta


# Candidatos a barrer (nombre, constructor(dseq), envuelto?). Pitch ABAJO = negativo.
def candidates():
    return [
        ("abs_angle w f=1 p=-30", lambda ds: N.gimbal_abs_angle_frame(ds, -300, flags=0x01), True),
        ("abs_angle b f=1 p=-30", lambda ds: N.gimbal_abs_angle_frame(ds, -300, flags=0x01), False),
        ("abs_angle w f=7 p=-30", lambda ds: N.gimbal_abs_angle_frame(ds, -300, flags=0x07), True),
        ("gimbal_ctrl w p=700",   lambda ds: N.gimbal_control_frame(ds, 700), True),
        ("gimbal_ctrl b p=700",   lambda ds: N.gimbal_control_frame(ds, 700), False),
        ("gimbal_ctrl w p=1350",  lambda ds: N.gimbal_control_frame(ds, 1350), True),
        ("gimbal_move w s=-60",   lambda ds: N.gimbal_move_frame(ds, -60), True),
        ("gimbal_move b s=-60",   lambda ds: N.gimbal_move_frame(ds, -60), False),
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", action="store_true",
                    help="solo LEE el angulo de la camara 20s, sin enviar comandos")
    ap.add_argument("--pitch", type=float, default=None,
                    help="APUNTA la camara a este angulo en grados (0=frente, neg=abajo, "
                         "pos=arriba) en lazo cerrado. Ej: --pitch -45")
    ap.add_argument("--secs", type=float, default=2.0, help="segundos por candidato (barrido)")
    args = ap.parse_args()

    s = N.Type5Session()
    print("=" * 64)
    print("  gimbal.py  —  CONTROL DE CAMARA (experimento en suelo, SIN volar)")
    print("=" * 64)
    if not s.open():
        print("SIN ack -> revisa WiFi del Neo / DJI Fly cerrado."); return
    print("hello -> ACK. Sesion abierta.")
    f = F.Flight(s)
    for fr in F.INIT:
        s.send_command(fr); time.sleep(0.03)
    ok = f.engage()
    print(">>> ENGANCHE 0x51: %s" % ("OK" if ok else "FALLO (no llego el serial)"), flush=True)

    if args.watch:
        print("--- solo lectura del angulo de la camara (20s) ---", flush=True)
        t0 = last = time.time()
        while time.time() - t0 < 20:
            p = read_pitch(f, 0.5)
            if p is not None:
                print("  camara pitch=%.1f  (abajo<0<arriba)" % p, flush=True)
        s.sock.close(); return

    if args.pitch is not None:
        print("--- APUNTANDO camara a pitch=%.1f (lazo cerrado)... ---" % args.pitch, flush=True)
        cur = f.read_gimbal(0.8)
        print("  angulo inicial: %s" % cur, flush=True)
        final = f.point_camera(args.pitch)
        print("  angulo final:   %s  (objetivo %.1f)" % (final, args.pitch), flush=True)
        if final is not None and abs(final - args.pitch) <= 3.0:
            print("  >>> OK: la camara quedo apuntando al objetivo.", flush=True)
        else:
            print("  (no llego al objetivo dentro del tiempo; sube el timeout o revisa limites)", flush=True)
        s.sock.close(); return

    print("--- barriendo candidatos de control (mira la CAMARA fisicamente) ---", flush=True)
    winners = []
    for name, fn, wrapped in candidates():
        moved, delta = try_candidate(f, name, fn, wrapped, args.secs)
        if moved:
            winners.append((name, delta))
    print("\n" + "=" * 64)
    if winners:
        print("CANDIDATOS QUE MOVIERON LA CAMARA:")
        for name, delta in winners:
            print("   %s  (delta=%+.1f)" % (name, delta))
        print("=> ese comando/envoltorio es el correcto; lo afinamos para apuntar a angulos.")
    else:
        print("Ninguno movio la camara. Siguiente: probar otros ejes/flags o capturar la app.")
    s.sock.close()


if __name__ == "__main__":
    main()
