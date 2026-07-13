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

    def send_command(self, mb):
        """Envia UN comando MB como type-5 con seq/ventanas correctas."""
        send_end = self.seq
        pkt = build_type5(self.session, self.seq, self.send_start, send_end, self.ctr, mb)
        self.sock.sendto(pkt, DRONE)
        sent_seq = self.seq
        self.seq = (self.seq + 8) & 0xffff
        self.ctr = (self.ctr + 1) & 0xff
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
        if w and w[0] > self.send_start:
            self.send_start = w[0]      # avanza nuestro send_start con el ACK del dron
        return w
