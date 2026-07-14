#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diag_authority.py — ¿El flight controller EJECUTA nuestros comandos, o solo los
acepta en el transporte? (EXP-025). SEGURO: no manda modo, ni AUTO_FLY, ni motores.
Solo consultas GET, que deberian provocar una RESPUESTA del dron si el FC nos oye.

Metodo: sesion viva -> init -> GetPlaneName (0x03/0x34) + GetFsAction (0x03/0x3c),
envueltos como la app -> escucha el DOWNLINK y decodifica todo frame DUML.
  - Si el dron responde 0x03/0x34 / 0x03/0x3c (snd=0x03) => el FC PROCESA lo nuestro.
  - Si solo hay status/keepalive y CERO respuesta a los GET => el FC nos IGNORA a
    nivel aplicacion aunque el transporte los acepte = problema de AUTORIDAD de sesion.
Tambien reporta que manda el dron en respuesta al init (por si hay un handshake que
no completamos).
"""
import socket, time, sys, os, collections
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "analysis"))
import neo_udp as N
from func_control_probe import scan_duml    # scan_duml(buf) -> (frame_fields, depth)
from flight import INIT

def drain(s, secs):
    """Escucha 'secs' y devuelve lista de (cset,cid,snd,rcv,depth,payload_hex)."""
    out = []
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
            out.append((m["cset"], m["cid"], m["snd"], m["rcv"], depth, m["payload"].hex()))
    return out

def summarize(label, frames):
    dn = collections.Counter()
    for cs, ci, snd, rcv, dep, pl in frames:
        # snd=0x03 => viene del flight controller (respuesta del dron)
        dn[(snd, cs, ci)] += 1
    print(f"  [{label}] DUML recibidos por (snd,cset,cid):")
    for (snd, cs, ci), n in sorted(dn.items(), key=lambda x: -x[1])[:20]:
        origen = "FC(0x03)" if snd == 0x03 else ("app-echo(0x02)" if snd == 0x02 else f"snd0x{snd:02x}")
        print(f"     {origen}  0x{cs:02x}/0x{ci:02x} : {n}")
    return dn

def main():
    s = N.Type5Session()
    print("=" * 60)
    print("diag_authority — ¿el FC ejecuta nuestros comandos? (sin motores)")
    if not s.open():
        print("SIN ack -> revisa WiFi del Neo / telefono fuera."); return
    print("hello -> ACK. sesion viva.")

    w = None
    for _ in range(10):
        w = s.poll(0.1)
        if w: break
    print("ventana RX baseline:", ("0x%04x" % w[0]) if w else "?")

    # 1) init + escucha (¿responde el dron al init?)
    print("\n-- enviando init (8 frames) y escuchando respuesta --")
    for fr in INIT:
        s.send_command(fr); time.sleep(0.03)
    init_dn = drain(s, 2.0)
    d1 = summarize("post-init", init_dn)

    # 2) GET commands (envueltos como la app), que DEBEN provocar respuesta
    print("\n-- enviando GETs: GetPlaneName 0x03/0x34 + GetFsAction 0x03/0x3c (envueltos) --")
    wd = 1
    dseq = 0xd000
    for _ in range(6):
        for inner in (N.get_plane_name_frame(dseq), N.get_fs_action_frame(dseq + 1)):
            s.send_command(N.wrap_5101(wd, inner)); wd += 1; dseq += 2
        time.sleep(0.15)
    get_dn = drain(s, 3.0)
    d2 = summarize("post-GET", get_dn)

    # 3) veredicto
    resp_34 = d2[(0x03, 0x03, 0x34)]
    resp_3c = d2[(0x03, 0x03, 0x3c)]
    wf = s.poll(0.2)
    print("\nventana RX final:", ("0x%04x" % wf[0]) if wf else "?", " (seq propio 0x%04x)" % s.seq)
    print("=" * 60)
    if resp_34 or resp_3c:
        print(f">>> EL FC RESPONDE A NUESTROS GET (0x34:{resp_34}, 0x3c:{resp_3c}).")
        print("    => El FC SI procesa nuestros comandos. El bloqueo es especifico del")
        print("       armado/modo, no de autoridad de sesion.")
    else:
        print(">>> CERO respuesta del FC (snd=0x03) a nuestros GET.")
        print("    => El FC IGNORA nuestros comandos a nivel aplicacion, aunque el")
        print("       transporte los acepte. Problema de AUTORIDAD de sesion (candidatos:")
        print("       handshake de init interactivo, session/UUID fresco, seq DUML).")
    s.sock.close()

if __name__ == "__main__":
    main()
