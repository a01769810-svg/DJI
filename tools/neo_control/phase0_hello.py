#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FASE 0 — Abrir sesion con el DJI Neo por UDP 9003 (solo HELLO + ACK).

QUE HACE (y que NO hace):
  - Envia el paquete "hello" (wrapper tipo 0x3080) al dron y escucha su respuesta.
  - Detecta el ACK del dron (0x0980) y/o sus keepalives (0x2280), que confirman
    que el dron ACEPTO nuestra sesion.
  - NO envia ningun comando de vuelo. NO mueve motores. NO arma. Es 100% pasivo
    salvo por el hello. Aun asi: manten el dron ASEGURADO y SIN HELICES.

REQUISITOS:
  - El PC debe estar unido a la WiFi del Neo (dron = 192.168.2.1, PC = 192.168.2.x).
  - El TELEFONO debe estar APAGADO / desconectado del dron (para no chocar: el Neo
    solo acepta un controlador a la vez).
  - Python 3. Sin dependencias externas.

USO:
  python phase0_hello.py                 # replay del hello capturado (session 4d6e)
  python phase0_hello.py --new-session   # genera un session ID propio aleatorio
  python phase0_hello.py --target 192.168.2.1 --listen 5
"""
import socket, argparse, sys, time, os

# Hello capturado del handshake real (Quinta prueba). Bytes 2-3 = session ID.
HELLO_HEX = "30804d6e00000093687264006400c005140000640000019001c005140000640014006400c00514000064000101040102"

def build_hello(session_id: bytes | None) -> bytes:
    b = bytearray.fromhex(HELLO_HEX)
    if session_id is not None:
        b[2:4] = session_id
    return bytes(b)

def describe(pkt: bytes) -> str:
    if len(pkt) < 4:
        return "paquete corto"
    typ = pkt[:2].hex()
    sess = pkt[2:4].hex()
    names = {"0980": "ACK de sesion", "2280": "keepalive/sync", "3080": "hello",
             "2180": "DUML init", "2680": "DUML init", "3680": "DUML init",
             "3d80": "STREAM de control"}
    return f"tipo={typ} ({names.get(typ,'?')}) sessID={sess}"

def main():
    ap = argparse.ArgumentParser(description="Fase 0: abrir sesion con el DJI Neo (hello+ack)")
    ap.add_argument("--target", default="192.168.2.1", help="IP del dron (default 192.168.2.1)")
    ap.add_argument("--port", type=int, default=9003, help="puerto UDP (default 9003)")
    ap.add_argument("--count", type=int, default=10, help="cuantos hello enviar (default 10)")
    ap.add_argument("--interval", type=float, default=0.2, help="segundos entre hellos (default 0.2)")
    ap.add_argument("--listen", type=float, default=4.0, help="segundos a escuchar tras el ultimo hello")
    ap.add_argument("--new-session", action="store_true", help="usar un session ID aleatorio propio")
    args = ap.parse_args()

    if args.new_session:
        session = os.urandom(2)
    else:
        session = bytes.fromhex("4d6e")
    hello = build_hello(session)

    print("="*64)
    print("  FASE 0 - abrir sesion DJI Neo (SOLO hello, sin comandos de vuelo)")
    print("  Manten el dron ASEGURADO y SIN HELICES. Telefono APAGADO.")
    print("="*64)
    print(f"  Destino     : {args.target}:{args.port}")
    print(f"  Session ID  : {session.hex()}  ({'aleatorio propio' if args.new_session else 'replay 4d6e'})")
    print(f"  Hello ({len(hello)}B): {hello.hex()}")
    print("-"*64)

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("0.0.0.0", 0))
    except OSError as e:
        print(f"[ERROR] no se pudo abrir socket: {e}"); sys.exit(1)
    local_port = s.getsockname()[1]
    print(f"  Escuchando en puerto local UDP {local_port}")
    s.settimeout(0.3)

    got_ack = False
    got_keepalive = 0
    replies = 0
    deadline = time.time() + args.count * args.interval + args.listen
    next_send = 0.0
    sent = 0
    while time.time() < deadline:
        now = time.time()
        if sent < args.count and now >= next_send:
            try:
                s.sendto(hello, (args.target, args.port))
                sent += 1
                print(f"  -> hello #{sent} enviado")
            except OSError as e:
                print(f"[ERROR] envio fallo: {e} (¿PC unido a la WiFi del Neo?)")
            next_send = now + args.interval
        try:
            data, addr = s.recvfrom(2048)
        except socket.timeout:
            continue
        except OSError:
            continue
        if addr[0] != args.target:
            continue
        replies += 1
        typ = data[:2].hex()
        echoed = data[2:4]
        tag = ""
        if typ == "0980":
            got_ack = True; tag = "  <<< ACK DE SESION"
        elif typ == "2280":
            got_keepalive += 1; tag = "  <<< keepalive del dron"
        match = " [sessID COINCIDE]" if echoed == session else f" [sessID dron={echoed.hex()}]"
        print(f"  <- {describe(data)}{match}  {data[:16].hex()}...{tag}")

    print("-"*64)
    print(f"  Respuestas del dron: {replies}  (ACK={got_ack}, keepalives={got_keepalive})")
    if got_ack or got_keepalive:
        print("  RESULTADO: EXITO  El dron ACEPTO nuestra sesion.")
        print("  => Podemos abrir sesion propia desde el PC. Listo para Fase 1 (init).")
    elif replies:
        print("  RESULTADO: PARCIAL - el dron respondio pero sin ACK/keepalive esperado.")
        print("  => Revisa los tipos recibidos arriba; quiza el hello necesita ajuste.")
    else:
        print("  RESULTADO: SIN RESPUESTA.")
        print("  Comprueba: (1) PC unido a la WiFi del Neo, (2) telefono apagado,")
        print("  (3) IP del dron correcta, (4) firewall de Windows permite Python UDP.")
    s.close()

if __name__ == "__main__":
    main()
