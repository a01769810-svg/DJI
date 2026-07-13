#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FASE 2c (path B, intento 2) - Init completo + autoridad 0x03/0x20 + DESPEGUE.

Reproduce la secuencia de arranque que hace DJI Fly antes de volar (EXP-010):
  1) hello -> ACK
  2) comandos de init (get-version 0x00/0x01, 0x00/0xb7, 0x11/0x4a, 0x00/0x51,
     0x07/0x93, 0x51/0x34, 0x18/0x37, 0x18/0x3c)  -- replay verbatim, sesion propia
  3) stream de autoridad 0x03/0x20 (estado 02 -> 03) + sticks NEUTRO + hello
  4) --fire: dispara el despegue 0x03/0xda 05 ffffffff

  >>> SEGURIDAD idem arm_takeoff: HELICES FUERA, dron fijado, boton de apagado a mano.
      Sin --fire: hace init + autoridad + neutro, NO despega (seguro, diagnostico).

USO:
  python init_takeoff.py           # init + autoridad + neutro (NO despega)
  python init_takeoff.py --fire     # ... y dispara el despegue
"""
import socket, time, argparse, collections

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

# init frames capturados (Quinta), se reenvian verbatim envueltos en NUESTRA sesion
INIT = [
    "550d0433020e95e5400001981f",                                             # 0x00/0x01 get-version
    "551204c7022899e54000b70101000c0094e0",                                   # 0x00/0xb7
    "552204ea02039ee540114a00000000000088d3c0000000000088d3c05f3b546af603",   # 0x11/0x4a
    "550e04660228aae54000510654fa",                                           # 0x00/0x51
    "552504840207cde5400793012b230032303230656534642d366163612d343636662d000e2f",  # 0x07/0x93 (UUID)
    "553304c2eee90200405134000402000032303230656534642d366163612d343636662d00000000000000000000000000006b21",  # 0x51/0x34
    "55430474cec80000001837010200000000000000000000000000010000000000000000000000000000000000000000000000000000000000000000000000000000b506",  # 0x18/0x37
    "553d041ecec8000040183c0d000400010500000000000000000102000000000000000000000000010100000000000000000000000000000000000033a4",  # 0x18/0x3c
]
FLYC20_DATA03 = bytes.fromhex("0e468601049b06fa")   # payload "estado 03" observado

def wrapper(n, total_len):
    tsfast = (0x9600 + n*0x20) & 0xffff
    tsmono = (0x00100000 + n*0x30) & 0xffffffff
    return (bytes([total_len & 0xff, 0x80]) + SESS + tsfast.to_bytes(2,'little')
            + bytes([0x05, n & 0xff]) + tsmono.to_bytes(4,'little')
            + bytes([0,0,0,0, n & 0xff, 0x01, 0,0]))

def wrap_frame(n, frame):
    return wrapper(n, 20 + len(frame)) + frame

def stick_frame(seq, r, p, th, y):
    V = (r&0x7ff)|((p&0x7ff)<<11)|((th&0x7ff)<<22)|((y&0x7ff)<<33)
    head = bytes([0x55,0x29,0x04,0xc9,0x02,0xa9]) + (seq&0xffff).to_bytes(2,'little') + bytes([0,1,0x0a,1,0x0d,0])
    tail = bytes([0x40,0,2,0,0,6,0x55,1,4,0x56,8,0,0,0,0,0,0,0,0])
    body = head + V.to_bytes(6,'little') + tail
    return body + crc16(body).to_bytes(2,'little')

def flyc20_frame(seq, state, data8, ctr):
    body = bytes([0x55,0x1a,0x04,0xb1,0x02,0x03]) + (seq&0xffff).to_bytes(2,'little') \
           + bytes([0x40,0x03,0x20, state&0xff]) + data8 + (ctr&0xffffffff).to_bytes(4,'little')
    return body + crc16(body).to_bytes(2,'little')

def takeoff_frame(seq):
    body = bytes([0x55,0x12,0x04,0xc7,0x02,0x03]) + (seq&0xffff).to_bytes(2,'little') \
           + bytes([0x40,0x03,0xda,0x05,0xff,0xff,0xff,0xff])
    return body + crc16(body).to_bytes(2,'little')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fire", action="store_true")
    args = ap.parse_args()

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("0.0.0.0", 0)); s.settimeout(0.02)

    got=False
    for _ in range(6):
        s.sendto(HELLO, DRONE); t0=time.time()
        while time.time()-t0 < 0.2:
            try:
                d,a=s.recvfrom(2048)
                if a[0]==DRONE[0] and d[:2].hex()=="0980": got=True
            except socket.timeout: pass
        if got: break
    print("hello ->", "ACK" if got else "SIN ack", flush=True)
    if not got: s.close(); return

    n=0
    types=collections.Counter(); tel=[]
    def send_frame(fr):
        nonlocal n
        s.sendto(wrap_frame(n, fr), DRONE); n+=1
    def drain():
        try:
            while True:
                d,a=s.recvfrom(2048)
                if a[0]==DRONE[0]:
                    ty=d[:2].hex(); types[ty]+=1
                    if ty=="8980" and len(tel)<6: tel.append(d.hex())
        except socket.timeout: pass

    # 2) init: get-version x3 + resto una vez
    print("2) enviando init...", flush=True)
    for _ in range(3):
        send_frame(bytes.fromhex(INIT[0])); time.sleep(0.03); drain()
    for h in INIT[1:]:
        send_frame(bytes.fromhex(h)); time.sleep(0.03); drain()

    # 3) stream: sticks NEUTRO @20Hz + 0x03/0x20 @1Hz + hello @2Hz
    ctr=0x6a545000
    def stream(secs, state, label, fire=False, ntimes=0):
        nonlocal n, ctr
        print(label, flush=True)
        end=time.time()+secs; nc=0.0; nh=0.0; nf=0.0; fired=0
        data = FLYC20_DATA03 if state==3 else bytes(8)
        while time.time()<end:
            now=time.time()
            if now>=nc:
                s.sendto(wrap_frame(n, stick_frame(n,1024,1024,1024,1024)), DRONE); n+=1
                nc=now+0.05
            if now>=nf:
                s.sendto(wrap_frame(n, flyc20_frame(n, state, data, ctr)), DRONE); n+=1; ctr+=1
                nf=now+1.0
            if fire and fired<ntimes and now>=0:
                s.sendto(wrap_frame(n, takeoff_frame(n)), DRONE); n+=1; fired+=1
                print("   >>> DESPEGUE enviado", fired, "/", ntimes, flush=True)
                fire=False if fired>=ntimes else fire
            if now>=nh:
                s.sendto(HELLO, DRONE); nh=now+0.5
            drain()

    stream(3.0, 2, "3) autoridad estado 02 + neutro (3 s)")
    stream(2.0, 3, "4) autoridad estado 03 + neutro (2 s)")

    if not args.fire:
        print("MODO SEGURO: init+autoridad hechos, NO se disparo despegue.")
        print("respuestas:", dict(types)); s.close(); return

    print("\n=== --fire: HELICES FUERA, boton de apagado a mano. 5s Ctrl+C ===", flush=True)
    for i in range(5,0,-1): print("  ",i, flush=True); time.sleep(1.0)
    try:
        stream(1.5, 3, ">>> DESPEGUE - MIRA LOS MOTORES <<<", fire=True, ntimes=3)
        stream(4.0, 3, "observando ~4 s (autoridad 03 + neutro)")
    finally:
        s.close()
    print("\nFIN. Si los motores siguen, APAGA EL DRON con su boton.")
    print("respuestas:", dict(types))
    for h in tel[:3]: print("tel8980:", h)

if __name__ == "__main__":
    main()
