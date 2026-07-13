#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
flight.py — Vuelo del DJI Neo con el wrapper CORREGIDO (EXP-018).

Reemplaza a vuelo.py (que usaba el wrapper roto). Construido sobre neo_udp.py.
Todos los frames DUML (init, sticks, autoridad, takeoff) estan VALIDADOS byte a
byte contra el vuelo real de la app (Quinta prueba.pcap).

Secuencia (fiel a lo que hace DJI Fly al despegar):
  hello -> init (8 frames verbatim) -> settle (sticks NEUTRO + autoridad 0x03/0x20)
  -> [SOLO con --fly --armed-ok] takeoff 0x03/0xda -> hover (neutro) -> land (throttle-min)

MODOS:
  (sin flags)         DRY RUN: abre sesion, init, y streamea NEUTRO + autoridad unos
                      segundos. NO despega, NO arma (neutro no arma). Confirma que la
                      ventana RX del dron avanza. SEGURO incluso en interior.
  --fly --armed-ok    VUELO REAL. Despega, flota, aterriza. REQUIERE los DOS flags.

SEGURIDAD (obligatoria para --fly):
  - EXTERIOR abierto, con GPS. Persona supervisando presente.
  - DJI Fly con failsafe = ATERRIZAR configurado de antemano.
  - Hélices puestas y firmes. Espacio despejado (nadie cerca).
  - CORTE DE EMERGENCIA REAL = boton de apagado del dron. Ctrl+C manda aterrizar,
    pero si el script muere, el failsafe del dron debe bajarlo.
  - NO hay comando de aterrizaje dedicado: se aterriza con throttle-min sostenido.

USO:
  python flight.py                       # DRY RUN seguro
  python flight.py --fly --armed-ok      # VUELO REAL (solo exterior/supervisado)
  python flight.py --fly --armed-ok --hover 4 --land 12
"""
import argparse, sys, time
import neo_udp as N

# --- Init verbatim capturado del vuelo real (Quinta), enviado como type-5 ---
INIT = [bytes.fromhex(h) for h in [
    "550d0433020e95e5400001981f",
    "551204c7022899e54000b70101000c0094e0",
    "552204ea02039ee540114a00000000000088d3c0000000000088d3c05f3b546af603",
    "550e04660228aae54000510654fa",
    "552504840207cde5400793012b230032303230656534642d366163612d343636662d000e2f",
    "553304c2eee90200405134000402000032303230656534642d366163612d343636662d00000000000000000000000000006b21",
    "55430474cec80000001837010200000000000000000000000000010000000000000000000000000000000000000000000000000000000000000000000000000000b506",
    "553d041ecec8000040183c0d000400010500000000000000000102000000000000000000000000010100000000000000000000000000000000000033a4",
]]

def _V(r, p, th, y):
    return (((r & 0x7ff) | ((p & 0x7ff) << 11) | ((th & 0x7ff) << 22) | ((y & 0x7ff) << 33))
            ).to_bytes(6, "little")

NEUTRAL = (1024, 1024, 1024, 1024)     # roll,pitch,thr,yaw centrados => hover, NO arma
THR_MIN = 364

class Flight:
    def __init__(self, sess):
        self.s = sess
        self.dseq = 0xe600            # secuencia DUML para los streams
        self.actr = 0x6a543b60        # contador de la autoridad 0x03/0x20

    def _dseq(self):
        v = self.dseq; self.dseq = (self.dseq + 1) & 0xffff; return v

    def stick(self, r, p, th, y):
        mb = N.mb_frame(0x02, 0xa9, self._dseq(), 0x00, 0x01, 0x0a,
                        b"\x01\x0d\x00" + _V(r, p, th, y) + b"\x40\x00\x02\x00\x00\x06\x55\x01\x04")
        return self.s.send_command(mb)

    def authority(self, state=0x02):
        mb = N.mb_frame(0x02, 0x03, self._dseq(), 0x40, 0x03, 0x20,
                        bytes([state]) + bytes(8) + self.actr.to_bytes(4, "little"))
        self.actr = (self.actr + 1) & 0xffffffff
        return self.s.send_command(mb)

    def takeoff(self):
        mb = N.mb_frame(0x02, 0x03, self._dseq(), 0x40, 0x03, 0xda, b"\x05\xff\xff\xff\xff")
        return self.s.send_command(mb)

    def set_mode(self, mode=N.MODE_MANUAL):
        return self.s.send_command(N.mode_frame(self._dseq(), mode))

    def stream(self, secs, sticks=None, mode=False, takeoff_once=False, label=""):
        """Streamea (opcional) sticks @20Hz + modo @10Hz + autoridad @1Hz durante 'secs'.
        sticks=None => no envia sticks (fase previa al vuelo). Devuelve ult. ventana RX."""
        if label: print(label, flush=True)
        end = time.time() + secs
        n_stick = n_auth = n_mode = n_ka = 0.0
        fired = not takeoff_once
        last_win = None
        while time.time() < end:
            now = time.time()
            if takeoff_once and not fired:
                self.takeoff(); fired = True; print("   >>> TAKEOFF (0x03/0xda) enviado", flush=True)
            if mode and now >= n_mode:
                self.set_mode(); n_mode = now + 0.1
            if sticks and now >= n_stick:
                self.stick(*sticks); n_stick = now + 0.05
            if now >= n_auth:
                self.authority(0x02); n_auth = now + 1.0
            if now >= n_ka:                # keepalive del hello ~cada 0.5s
                self.s.keepalive(); n_ka = now + 0.5
            w = self.s.poll(0.01)
            if w: last_win = w
        return last_win


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fly", action="store_true", help="ejecutar VUELO REAL (motores)")
    ap.add_argument("--armed-ok", dest="armed_ok", action="store_true",
                    help="2do candado: confirma exterior+supervisado+failsafe")
    ap.add_argument("--settle", type=float, default=3.0)
    ap.add_argument("--hover", type=float, default=4.0)
    ap.add_argument("--land", type=float, default=12.0)
    args = ap.parse_args()

    real = args.fly and args.armed_ok
    if args.fly and not args.armed_ok:
        print("!! --fly requiere tambien --armed-ok (confirmacion de seguridad). Abortado.")
        sys.exit(1)

    s = N.Type5Session()
    print("=" * 62)
    print("  flight.py  —  %s" % ("VUELO REAL (motores)" if real else "DRY RUN (sin despegue)"))
    print("  seed=0x%04x primer seq=0x%04x session=0x%04x" % (s.seed, s.seq, s.session))
    print("=" * 62)
    if not s.open():
        print("SIN ack -> revisa WiFi del Neo / DJI Fly cerrado."); sys.exit(1)
    print("hello -> ACK. Sesion abierta.")

    base = None
    for _ in range(10):
        w = s.poll(0.1)
        if w: base = w; break
    print("ventana RX type-5 baseline:", "0x%04x" % base[0] if base else "?")

    f = Flight(s)
    print("enviando init (%d frames)..." % len(INIT))
    for fr in INIT:
        f.s.send_command(fr); time.sleep(0.03)

    if not real:
        f.stream(1.5, mode=True, label="0) fijando MODO MANUAL (0x03/0xf9)...")
        win = f.stream(args.settle + 2.0, NEUTRAL, mode=True, label="DRY RUN: modo+NEUTRO+autoridad (NO despega)...")
        print("ventana RX final:", "0x%04x" % win[0] if win else "?")
        if base and win:
            print(">>> %s" % ("VENTANA AVANZO (0x%04x->0x%04x): secuencia de vuelo ACEPTADA. Listo para --fly EXTERIOR."
                  % (base[0], win[0]) if win[0] > base[0] else "ventana NO avanzo: revisar."))
        s.sock.close(); return

    # ---- VUELO REAL ----
    print("\n" + "!" * 62)
    print(" VUELO REAL. EXTERIOR + SUPERVISADO + failsafe=Aterrizar.")
    print(" Ctrl+C = ATERRIZAR. Corte real = BOTON del dron.")
    print("!" * 62, flush=True)
    try:
        f.stream(1.5, mode=True, label="0) fijando MODO MANUAL (0x03/0xf9)...")
        f.stream(args.settle, NEUTRAL, mode=True, label="1) settle: modo + neutro + autoridad")
        print(">>> DESPEGUE en 5 s (Ctrl+C aborta)...", flush=True)
        for i in range(5, 0, -1):
            print("   ", i, flush=True); time.sleep(1.0)
        wtk = f.stream(args.hover, NEUTRAL, mode=True, takeoff_once=True, label="2) DESPEGUE + HOVER (neutro, modo Manual)")
        print("   ventana RX t5 tras takeoff+hover:", ("0x%04x" % wtk[0]) if wtk else "?",
              "(seq propio ~0x%04x)" % f.s.seq, flush=True)
        print(">>> ATERRIZANDO: throttle-min. Mira descender...", flush=True)
        f.stream(args.land, (1024, 1024, THR_MIN, 1024), label="")
        print(">>> Fin. Si sigue en el aire: BOTON del dron o failsafe.", flush=True)
    except KeyboardInterrupt:
        print("\n!! ABORTO -> aterrizando (throttle-min)", flush=True)
        try:
            f.stream(args.land, (1024, 1024, THR_MIN, 1024))
        except KeyboardInterrupt:
            print("Saliendo. Failsafe=Aterrizar deberia bajarlo; si no, BOTON del dron.")
    finally:
        s.sock.close()
    print("FIN del vuelo.")

if __name__ == "__main__":
    main()
