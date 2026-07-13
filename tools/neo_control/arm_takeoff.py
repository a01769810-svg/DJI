#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FASE 2b (path B) - Inyeccion del comando de DESPEGUE real del DJI Neo.

  Comando: DUML cmd_set 0x03 / cmd_id 0xda, payload 05 ffffffff  (EXP-010).
  Es el "one-tap takeoff" real extraido del vuelo Quinta (unico en todo el vuelo,
  ~60 ms antes de arrancar el stream de sticks).

  >>>>>>>>>>>>>>>>>>>>>>>>  SEGURIDAD - LEER  <<<<<<<<<<<<<<<<<<<<<<<<
  ESTE SCRIPT PUEDE HACER GIRAR LOS MOTORES A POTENCIA DE DESPEGUE.
  - HELICES FUERA (obligatorio). Sin helices no hay empuje aunque los motores giren.
  - Dron FIJADO firme a algo pesado/inmovil. Manos y cara LEJOS.
  - EL CORTE FIABLE ES EL BOTON DE ENCENDIDO DEL DRON (mantener pulsado para apagar).
    Ctrl+C / cerrar el script puede NO parar los motores si el dron se cree "volando"
    (podria entrar en failsafe/hover). Ten el boton de apagado a la mano.
  - Telefono en la WiFi del Neo, DJI Fly CERRADO.

  Sin --fire NO envia el despegue: solo abre sesion y streamea NEUTRO (seguro),
  util para confirmar que la sesion sigue viva. El despegue solo se dispara con --fire.

USO:
  python arm_takeoff.py            # SEGURO: solo neutro, NO despega
  python arm_takeoff.py --fire     # dispara el comando de despegue (motores!)
"""
import socket, time, argparse, collections

# --- CRC por formula (verificados contra tramas reales, EXP-007/010) ---
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

def wrapper(n, total_len):
    """20-byte wrapper de sesion. byte0 = longitud total del paquete UDP."""
    tsfast = (0x9600 + n*0x20) & 0xffff
    tsmono = (0x00100000 + n*0x30) & 0xffffffff
    return (bytes([total_len & 0xff, 0x80]) + SESS + tsfast.to_bytes(2,'little')
            + bytes([0x05, n & 0xff]) + tsmono.to_bytes(4,'little')
            + bytes([0,0,0,0, n & 0xff, 0x01, 0,0]))

def stick_frame(seq, roll, pitch, thr, yaw):
    V = (roll & 0x7ff) | ((pitch & 0x7ff) << 11) | ((thr & 0x7ff) << 22) | ((yaw & 0x7ff) << 33)
    head = bytes([0x55,0x29,0x04,0xc9,0x02,0xa9]) + (seq & 0xffff).to_bytes(2,'little') + bytes([0x00,0x01,0x0a,0x01,0x0d,0x00])
    chan = V.to_bytes(6,'little')
    tail = bytes([0x40,0x00,0x02,0x00,0x00,0x06,0x55,0x01,0x04,0x56,0x08, 0x00,0x00, 0x00,0x00,0x00,0x00,0x00,0x00])
    body = head + chan + tail
    return body + crc16(body).to_bytes(2,'little')          # 41 bytes

def stick_pkt(n, roll=1024, pitch=1024, thr=1024, yaw=1024):
    fr = stick_frame(n, roll, pitch, thr, yaw)
    return wrapper(n, 20 + len(fr)) + fr                    # 61 bytes

def takeoff_frame(seq):
    """DUML 0x03/0xda payload 05 ffffffff con nuestro seq (EXP-010)."""
    body = bytes([0x55,0x12,0x04,0xc7,0x02,0x03]) + (seq & 0xffff).to_bytes(2,'little') \
           + bytes([0x40,0x03,0xda,0x05,0xff,0xff,0xff,0xff])
    return body + crc16(body).to_bytes(2,'little')          # 18 bytes

def takeoff_pkt(n):
    fr = takeoff_frame(n)
    return wrapper(n, 20 + len(fr)) + fr                    # 38 bytes

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fire", action="store_true", help="dispara el comando de DESPEGUE (motores)")
    args = ap.parse_args()

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("0.0.0.0", 0)); s.settimeout(0.02)

    # 1) hello + ack
    got=False
    for _ in range(6):
        s.sendto(HELLO, DRONE); t0=time.time()
        while time.time()-t0 < 0.2:
            try:
                d,a=s.recvfrom(2048)
                if a[0]==DRONE[0] and d[:2].hex()=="0980": got=True
            except socket.timeout: pass
        if got: break
    print("hello ->", "ACK (sesion abierta)" if got else "SIN ack - revisa WiFi/DJI Fly", flush=True)
    if not got:
        s.close(); return

    n=0
    types=collections.Counter()
    def pump(seconds, label, roll=1024, pitch=1024, thr=1024, yaw=1024, fire=False, fire_times=0):
        nonlocal n
        print(label, flush=True)
        end=time.time()+seconds; nc=0.0; nh=0.0; fired=0
        while time.time()<end:
            now=time.time()
            if now>=nc:
                s.sendto(stick_pkt(n, roll,pitch,thr,yaw), DRONE); n+=1; nc=now+0.04
                if fire and fired<fire_times:
                    s.sendto(takeoff_pkt(n), DRONE); n+=1; fired+=1
                    print("   >>> DESPEGUE enviado (%d/%d)" % (fired, fire_times), flush=True)
            if now>=nh:
                s.sendto(HELLO, DRONE); nh=now+0.5
            try:
                d,a=s.recvfrom(2048)
                if a[0]==DRONE[0]: types[d[:2].hex()]+=1
            except socket.timeout: pass

    if not args.fire:
        pump(6.0, "MODO SEGURO (sin --fire): solo NEUTRO, NO despega.")
        print("respuestas:", dict(types)); s.close(); return

    print("\n" + "="*56)
    print("  --fire ACTIVO. HELICES FUERA. Boton de apagado a la mano.")
    print("  Empieza en 5 s (Ctrl+C para abortar)...")
    print("="*56, flush=True)
    for i in range(5,0,-1):
        print("  ", i, flush=True); time.sleep(1.0)
    try:
        pump(2.5, "1) NEUTRO (estableciendo control, throttle centro)")
        pump(1.0, ">>> 2) DESPEGUE - MIRA LOS MOTORES <<<", fire=True, fire_times=3)
        pump(4.0, "3) NEUTRO (observando ~4 s)")
    finally:
        s.close()
    print("\nFIN del script. Si los motores siguen girando, APAGA EL DRON con su boton.")
    print("respuestas del dron:", dict(types))

if __name__ == "__main__":
    main()
