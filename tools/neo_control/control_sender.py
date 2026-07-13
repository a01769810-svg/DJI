#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FASE 2a - Emisor de control del DJI Neo (por defecto: NEUTRO, sin movimiento).

Envia el hello, mantiene la sesion, y streamea tramas de STICKS 0x01/0x0a a ~20 Hz.
Por defecto los 4 ejes van a 1024 (centrado) => NO arma, NO mueve motores.
Sirve para confirmar que el dron ACEPTA nuestras tramas de control forjadas.

  ch0=ROLL  ch1=PITCH  ch2=THROTTLE  ch3=YAW    (364=min, 1024=centro, 1684=max)

SEGURIDAD:
  - QUITA LAS HELICES antes de correrlo. Dron asegurado, telefono en WiFi del Neo,
    DJI Fly CERRADO.
  - Esta version manda SOLO NEUTRO. No hay armado ni throttle. Aun asi, hélices fuera.

USO:
  python control_sender.py            # 8 s de control NEUTRO + reporte
  python control_sender.py --secs 15
"""
import socket, time, argparse

# --- CRC generables por formula (verificados contra trama real) ---
def _tab(poly):
    t=[]
    for i in range(256):
        c=i
        for _ in range(8): c=(c>>1)^poly if c&1 else c>>1
        t.append(c)
    return t
T8=_tab(0x8c); T16=_tab(0x8408)
def crc8(d, c=0x77):
    for b in d: c=T8[(b^c)&0xff]
    return c
def crc16(d, v=0x3692):
    for b in d: v=(v>>8)^T16[(b^v)&0xff]
    return v & 0xffff

SESS  = bytes.fromhex("4d6e")
HELLO = bytes.fromhex("30804d6e00000093687264006400c005140000640000019001c005140000640014006400c00514000064000101040102")
DRONE = ("192.168.2.1", 9003)

def stick_frame(seq, roll, pitch, thr, yaw):
    """41-byte DUML 0x01/0x0a con 4 canales de 11 bits."""
    V = (roll & 0x7ff) | ((pitch & 0x7ff) << 11) | ((thr & 0x7ff) << 22) | ((yaw & 0x7ff) << 33)
    head = bytes([0x55,0x29,0x04,0xc9,0x02,0xa9]) + (seq & 0xffff).to_bytes(2,'little') + bytes([0x00,0x01,0x0a,0x01,0x0d,0x00])
    chan = V.to_bytes(6,'little')
    tail = bytes([0x40,0x00,0x02,0x00,0x00,0x06,0x55,0x01,0x04,0x56,0x08, 0x00,0x00, 0x00,0x00,0x00,0x00,0x00,0x00])
    body = head + chan + tail            # 39 bytes
    return body + crc16(body).to_bytes(2,'little')   # +crc16 = 41

def wrapper(n):
    """20-byte wrapper de sesion con contadores incrementales."""
    tsfast = (0x9600 + n*0x20) & 0xffff
    tsmono = (0x00100000 + n*0x30) & 0xffffffff
    return (bytes([0x3d,0x80]) + SESS + tsfast.to_bytes(2,'little')
            + bytes([0x05, n & 0xff]) + tsmono.to_bytes(4,'little')
            + bytes([0,0,0,0, n & 0xff, 0x01, 0,0]))

def control_packet(n, roll=1024, pitch=1024, thr=1024, yaw=1024):
    return wrapper(n) + stick_frame(n, roll, pitch, thr, yaw)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--secs", type=float, default=8.0)
    args = ap.parse_args()

    print("="*60)
    print("  FASE 2a - control NEUTRO (todos los ejes = 1024)")
    print("  QUITA LAS HELICES. No arma ni mueve motores. Solo valida aceptacion.")
    print("="*60)

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("0.0.0.0", 0)); s.settimeout(0.05)

    # 1) hello + esperar ack
    got_ack=False
    for _ in range(5):
        s.sendto(HELLO, DRONE)
        t0=time.time()
        while time.time()-t0 < 0.2:
            try:
                d,a=s.recvfrom(2048)
                if a[0]==DRONE[0] and d[:2].hex()=="0980": got_ack=True
            except socket.timeout: pass
        if got_ack: break
    print("hello ->", "ACK recibido" if got_ack else "SIN ack (revisa WiFi/DJI Fly)")

    # 2) stream NEUTRO ~20 Hz + keepalive; contar respuestas y muestrear telemetria
    import collections
    types=collections.Counter(); tel=[]
    n=0; end=time.time()+args.secs; next_ctrl=0.0; next_hello=0.0
    print(f"streameando control NEUTRO {args.secs}s...")
    while time.time()<end:
        now=time.time()
        if now>=next_ctrl:
            s.sendto(control_packet(n), DRONE); n+=1; next_ctrl=now+0.05
        if now>=next_hello:
            s.sendto(HELLO, DRONE); next_hello=now+0.5
        try:
            d,a=s.recvfrom(2048)
        except socket.timeout:
            continue
        if a[0]!=DRONE[0]: continue
        ty=d[:2].hex(); types[ty]+=1
        if ty=="8980" and len(tel)<4: tel.append(d.hex())
    print(f"tramas de control enviadas: {n}")
    print("respuestas del dron por tipo:", dict(types))
    print("sesion", "VIVA (dron sigue respondiendo bajo control)" if types else "SIN respuesta")
    for h in tel:
        print("tel8980:", h)

if __name__=="__main__":
    main()
