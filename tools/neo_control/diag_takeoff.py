#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[DEPRECADO — EXP-024] NO USAR. El "TAKEOFF" aqui es 0x03/0xda (Detection), NO despegue.
  El despegue real es FunctionControl 0x03/0x2a:01 AUTO_FLY. Wrapper viejo (EXP-018).
  Reemplazado por flight.py + neo_udp.py.

diag_takeoff.py — Diagnostico: que responde el Neo al comando de despegue.

Abre sesion, init, fija modo Manual, y luego envia el TAKEOFF + stream de hover
mientras REGISTRA el downlink del dron: tipos de paquete, avance de la ventana RX
type-5 (si acepta nuestros comandos en transporte) y si el estado en su telemetria
type-1 cambia antes/despues del takeoff.

No es un candado de vuelo: si el dron SI despegara aqui, despegaria. En interior
amplio y supervisado. Corte real = boton del dron.
"""
import sys, time, collections
sys.path.insert(0, ".")
import neo_udp as N
from flight import Flight, INIT, NEUTRAL

def recv_types(sock, dur):
    """Escucha 'dur' s; devuelve (Counter de tipos, muestras de type-1, ult. ventana RX t5)."""
    types = collections.Counter(); t1 = []; win = None
    end = time.time() + dur
    while time.time() < end:
        sock.settimeout(0.05)
        try:
            d, a = sock.recvfrom(4096)
        except Exception:
            continue
        if a[0] != N.DRONE[0] or len(d) < 8:
            continue
        types[d[6]] += 1
        if d[6] == 0x01:
            w = N.drone_type5_recv_window(d)
            if w: win = w
            if len(t1) < 2:
                t1.append(d[:40].hex())
    return types, t1, win

def main():
    s = N.Type5Session()
    print("=" * 60)
    print("  diag_takeoff — que responde el Neo al despegue")
    print("  seed=0x%04x seq0=0x%04x session=0x%04x" % (s.seed, s.seq, s.session))
    print("=" * 60)
    if not s.open():
        print("SIN ack."); return
    print("hello -> ACK.")
    f = Flight(s)
    for fr in INIT:
        s.send_command(fr); time.sleep(0.03)
    print("init enviado (%d frames)." % len(INIT))

    # Fijar modo Manual (burst)
    print("fijando modo Manual...")
    end = time.time() + 1.5
    while time.time() < end:
        f.set_mode(); time.sleep(0.04)
        try:
            s.sock.settimeout(0.003); s.sock.recvfrom(4096)
        except Exception:
            pass

    # Downlink ANTES del takeoff (con neutro + autoridad corriendo)
    print("\n-- capturando downlink ANTES del takeoff (2s, neutro+autoridad) --")
    tprev = time.time() + 2.0
    na = 0.0
    while time.time() < tprev:
        now = time.time()
        if now >= na:
            f.authority(0x02); na = now + 1.0
        f.stick(*NEUTRAL)
        time.sleep(0.05)
    types_b, t1_b, win_b = recv_types(s.sock, 1.5)
    print("  tipos downlink:", dict(types_b))
    print("  ventana RX t5:", ("0x%04x" % win_b[0]) if win_b else "?")
    for x in t1_b: print("  type1:", x)

    # TAKEOFF + hover, capturando downlink en vivo
    print("\n-- enviando TAKEOFF (0x03/0xda) + hover 6s, capturando downlink --")
    f.takeoff(); print("   >>> TAKEOFF enviado")
    types_a = collections.Counter(); t1_a = []; win_a = None
    end = time.time() + 6.0
    ns = na = nm = 0.0
    while time.time() < end:
        now = time.time()
        if now >= nm: f.set_mode(); nm = now + 0.1
        if now >= ns: f.stick(*NEUTRAL); ns = now + 0.05
        if now >= na: f.authority(0x02); na = now + 1.0
        s.sock.settimeout(0.01)
        try:
            d, a = s.sock.recvfrom(4096)
        except Exception:
            continue
        if a[0] != N.DRONE[0] or len(d) < 8: continue
        types_a[d[6]] += 1
        if d[6] == 0x01:
            w = N.drone_type5_recv_window(d)
            if w: win_a = w
            if len(t1_a) < 3: t1_a.append(d[:40].hex())

    print("  tipos downlink DURANTE/POST takeoff:", dict(types_a))
    print("  ventana RX t5:", ("0x%04x" % win_a[0]) if win_a else "?")
    for x in t1_a: print("  type1:", x)

    print("\n-- LECTURA --")
    if win_b and win_a:
        print("  ventana RX avanzo con el takeoff:" ,
              "SI (0x%04x->0x%04x) => transporte acepta el comando" % (win_b[0], win_a[0])
              if win_a[0] > win_b[0] else "NO")
    print("  aparecio VIDEO (type 0x02)?:", "SI => esta volando/armado" if types_a.get(0x02) else "no")
    print("  type1 cambio (estado):", "posible cambio" if t1_b and t1_a and t1_b[0] != t1_a[0] else "sin cambio visible")
    s.sock.close()

if __name__ == "__main__":
    main()
