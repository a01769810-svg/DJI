#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
set_mode.py — PRIMER experimento fisico seguro tras el fix del wrapper (EXP-018).

Envia el comando de MODO DE VUELO Manual (cmd_set 0x03 / cmd_id 0xf9 / modo 0x09)
usando el wrapper type-5 CORRECTO (seq=seed+8, +8, XOR ok, ventanas coherentes).

NO despega, NO arma, NO mueve motores. Solo cambia el modo (inocuo).

CRITERIO DE EXITO OBSERVABLE (sin tocar el dron):
  El dron reporta su ventana RX type-5 en sus paquetes type-1 (offset 0x18-0x1b).
  - Si tras enviar el comando esa ventana AVANZA por encima de nuestro seq
    (0x7270+), el dron ACEPTO nuestro comando en la capa de UDP fiable
    (por primera vez). Antes del fix quedaba CONGELADA en el seed (0x7268).
  => Ese avance es la prueba de que el fix funciona, sin riesgo fisico alguno.

USO (PC ya unida a la WiFi del Neo, DJI Fly cerrado, telefono fuera del Neo):
  python set_mode.py            # manda modo Manual y reporta si la ventana avanza
  python set_mode.py --secs 6
"""
import argparse, time
import neo_udp as N

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--secs", type=float, default=5.0)
    ap.add_argument("--mode", type=lambda s: int(s, 0), default=N.MODE_MANUAL)
    args = ap.parse_args()

    s = N.Type5Session()
    print("=" * 62)
    print("  set_mode — comando de MODO (inocuo). NO vuela, NO motores.")
    print("  seed=0x%04x  primer type5 seq=0x%04x  session=0x%04x"
          % (s.seed, s.seq, s.session))
    print("=" * 62)

    if not s.open():
        print("SIN ack -> revisa que la PC este en la WiFi del Neo y DJI Fly cerrado.")
        return
    print("hello -> ACK. Sesion abierta.")

    # baseline de la ventana RX type-5 del dron
    base = None
    t0 = time.time()
    while time.time() - t0 < 1.0 and base is None:
        w = s.poll(0.1)
        if w:
            base = w
    print("ventana RX type-5 del dron (baseline):",
          "0x%04x..0x%04x" % base if base else "no recibida")

    # stream del comando de modo + keepalives; observa la ventana
    dseq = 0xd2e4
    end = time.time() + args.secs
    next_cmd = 0.0; next_ka = 0.0
    sent = []; last_win = base
    while time.time() < end:
        now = time.time()
        if now >= next_cmd:
            frame = N.mode_frame(dseq, args.mode); dseq = (dseq + 1) & 0xffff
            seq = s.send_command(frame); sent.append(seq)
            next_cmd = now + 0.05                       # ~20 Hz como la app
        if now >= next_ka:
            s.keepalive(); next_ka = now + 0.5
        w = s.poll(0.02)
        if w:
            last_win = w

    lo = sent[0] if sent else None
    hi = sent[-1] if sent else None
    print("comandos de modo enviados: %d  (seq 0x%04x..0x%04x)"
          % (len(sent), lo, hi))
    print("ventana RX type-5 del dron (final):",
          "0x%04x..0x%04x" % last_win if last_win else "no recibida")

    if base and last_win:
        advanced = last_win[0] > base[0]
        print("\n>>> RESULTADO:",
              "VENTANA AVANZO (0x%04x -> 0x%04x) => el dron ACEPTO el comando type-5. FIX OK."
              % (base[0], last_win[0]) if advanced else
              "ventana NO avanzo (sigue en 0x%04x) => comando aun rechazado; revisar." % base[0])
    print("\n(Comprobar aparte en telemetria si el MODO cambio a Manual; el avance de\n"
          " la ventana ya confirma aceptacion a nivel de transporte.)")

if __name__ == "__main__":
    main()
