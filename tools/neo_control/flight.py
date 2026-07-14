#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
flight.py — Vuelo del DJI Neo reproduciendo FIELMENTE la secuencia de la app
(EXP-021). Wrapper UDP fiable corregido (EXP-018) + armado completo.

Secuencia objetivo (fiel a DJI Fly, validada byte a byte por
analysis/validate_arm.py contra Quinta y Octava):

  HELLO -> reliable-UDP (type-5) -> init (8 frames verbatim)
        -> [settle] autoridad 0x03/0x20 var-02 + modo Manual 0x03/0xf9 + sticks NEUTRO
        -> autoridad var-03 (coordenada GPS, grados*1e6 — pasada por CLI, NO hardcodeada)
        -> lote de parametros 0x03/0xf8
        -> [--fly] rafaga de armado (0x03/0x34, 0x03/0x3c, 0x0d/0x03) + despegue 0x03/0xda
        -> heartbeat de vuelo 0x03/0xd7 (continuo) + sticks NEUTRO (hover)
        -> aterrizaje: throttle-min sostenido

Todos los frames DUML se construyen con builders VALIDADOS en neo_udp.py.

MODOS:
  (sin flags)         DRY RUN: ejecuta TODA la secuencia MENOS el despegue 0x03/0xda.
                      Manda init, autoridad (var-02/03), 0x03/0xf8, rafaga de armado,
                      modo, heartbeat y sticks NEUTRO. Sirve para confirmar que el dron
                      ACEPTA cada frame (su ventana RX type-5 avanza) SIN armar motores.
                      SEGURO en interior.
  --fly --armed-ok    VUELO REAL: incluye el despegue. REQUIERE los DOS flags.

Coordenada de autoridad var-03 (privacidad):
  --lat / --lon en grados decimales. Se pasan en tiempo de ejecucion, NO se guardan
  en el repo. Sin ellas, la autoridad se queda en var-02 (coord en cero) y se avisa.

SEGURIDAD (obligatoria para --fly):
  - EXTERIOR abierto con GPS. Persona supervisando. Espacio despejado.
  - DJI Fly con failsafe = ATERRIZAR configurado de antemano.
  - Helices firmes. Corte de emergencia real = BOTON del dron (Ctrl+C manda aterrizar).
  - No hay comando de aterrizaje dedicado fiable: se baja con throttle-min sostenido.

USO:
  python flight.py                                   # DRY RUN seguro (todo menos despegue)
  python flight.py --lat 19.4326 --lon -99.1332      # DRY con autoridad var-03
  python flight.py --fly --armed-ok --lat .. --lon .. # VUELO REAL (solo exterior/supervisado)
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

def deg_to_e6(d):
    """grados decimales -> int32 grados*1e6 (formato de la autoridad var-03)."""
    return int(round(d * 1_000_000))

class Flight:
    def __init__(self, sess, lat=None, lon=None):
        self.s = sess
        self.dseq = 0xe600
        self.hb = 0                       # contador del heartbeat 0x03/0xd7
        self.hb_started = False
        # autoridad var-03 solo si hay coordenada; si no, var-02
        self.auth_state = 0x03 if (lat is not None and lon is not None) else 0x02
        self.lat_e6 = deg_to_e6(lat) if lat is not None else 0
        self.lon_e6 = deg_to_e6(lon) if lon is not None else 0

    def _dseq(self):
        v = self.dseq; self.dseq = (self.dseq + 1) & 0xffff; return v

    def stick(self, r, p, th, y):
        mb = N.mb_frame(0x02, 0xa9, self._dseq(), 0x00, 0x01, 0x0a,
                        b"\x01\x0d\x00" + _V(r, p, th, y) + b"\x40\x00\x02\x00\x00\x06\x55\x01\x04")
        return self.s.send_command(mb)

    def authority(self):
        # ts = timestamp Unix real (el contador de la autoridad es la hora en segundos)
        ts = int(time.time())
        return self.s.send_command(
            N.authority_frame(self._dseq(), ts, self.auth_state, self.lat_e6, self.lon_e6))

    def set_mode(self, mode=N.MODE_MANUAL):
        return self.s.send_command(N.mode_frame(self._dseq(), mode))

    def f8(self):
        return self.s.send_command(N.f8_frame(self._dseq()))

    def arm_burst(self):
        """Rafaga que la app manda junto al despegue (no arma por si sola)."""
        self.s.send_command(N.arm34_frame(self._dseq()))
        self.s.send_command(N.arm3c_frame(self._dseq()))
        self.s.send_command(N.arm0d03_frame(self._dseq()))

    def takeoff(self):
        return self.s.send_command(N.takeoff_frame(self._dseq()))

    def heartbeat(self):
        if not self.hb_started:
            self.hb_started = True
            return self.s.send_command(N.d7_frame(self._dseq(), 0, init=True))
        r = self.s.send_command(N.d7_frame(self._dseq(), self.hb))
        self.hb = (self.hb + 1) & 0xffffffff
        return r

    def stream(self, secs, sticks=None, mode=False, auth=True, hb=False,
               takeoff_hold=False, label=""):
        """Streamea durante 'secs' varias 'pistas' a su frecuencia observada:
             sticks 20Hz · modo 10Hz · heartbeat d7 10Hz · autoridad 1Hz · keepalive 2Hz.
           takeoff_hold=True: repite 0x03/0xda ~15Hz (imita 'mantener' el boton).
           Devuelve la ultima ventana RX type-5 del dron."""
        if label: print(label, flush=True)
        end = time.time() + secs
        nt = {"stick": 0.0, "mode": 0.0, "hb": 0.0, "auth": 0.0, "ka": 0.0, "tk": 0.0}
        last_win = None
        while time.time() < end:
            now = time.time()
            if takeoff_hold and now >= nt["tk"]:
                self.takeoff(); nt["tk"] = now + 0.07
            if mode and now >= nt["mode"]:
                self.set_mode(); nt["mode"] = now + 0.1
            if hb and now >= nt["hb"]:
                self.heartbeat(); nt["hb"] = now + 0.1
            if sticks and now >= nt["stick"]:
                self.stick(*sticks); nt["stick"] = now + 0.05
            if auth and now >= nt["auth"]:
                self.authority(); nt["auth"] = now + 1.0
            if now >= nt["ka"]:
                self.s.keepalive(); nt["ka"] = now + 0.5
            w = self.s.poll(0.01)
            if w: last_win = w
        return last_win


def run_common(f, args):
    """init + settle + autoridad(var-03) + 0x03/0xf8 + rafaga de armado.
       Comun a DRY y a --fly. NO incluye el despegue 0x03/0xda."""
    print("enviando init (%d frames)..." % len(INIT))
    for fr in INIT:
        f.s.send_command(fr); time.sleep(0.03)
    f.stream(1.5, mode=True, auth=True, label="0) fijando MODO MANUAL + autoridad...")
    f.stream(args.settle, NEUTRAL, mode=True,
             label="1) settle: modo + NEUTRO + autoridad var-0%d" % f.auth_state)
    print("2) lote de parametros 0x03/0xf8 + rafaga de armado (0x03/0x34,0x3c,0x0d/03)...", flush=True)
    f.f8(); f.arm_burst()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fly", action="store_true", help="ejecutar VUELO REAL (motores)")
    ap.add_argument("--armed-ok", dest="armed_ok", action="store_true",
                    help="2do candado: confirma exterior+supervisado+failsafe")
    ap.add_argument("--lat", type=float, default=None, help="latitud grados (autoridad var-03)")
    ap.add_argument("--lon", type=float, default=None, help="longitud grados (autoridad var-03)")
    ap.add_argument("--settle", type=float, default=4.0)
    ap.add_argument("--tkhold", type=float, default=3.0, help="segundos de 'hold' del despegue")
    ap.add_argument("--hover", type=float, default=3.0)
    ap.add_argument("--land", type=float, default=12.0)
    args = ap.parse_args()

    real = args.fly and args.armed_ok
    if args.fly and not args.armed_ok:
        print("!! --fly requiere tambien --armed-ok (confirmacion de seguridad). Abortado.")
        sys.exit(1)

    s = N.Type5Session()
    print("=" * 64)
    print("  flight.py  —  %s" % ("VUELO REAL (motores)" if real else "DRY RUN (sin despegue)"))
    print("  seed=0x%04x primer seq=0x%04x session=0x%04x" % (s.seed, s.seq, s.session))
    if args.lat is None or args.lon is None:
        print("  !! sin --lat/--lon -> autoridad en VAR-02 (coord en cero).")
        print("     EXP-020 sugiere que el armado usa VAR-03 con coordenada; pasa --lat/--lon.")
    else:
        print("  autoridad VAR-03 con coordenada provista (no se registra el valor).")
    print("=" * 64)
    if not s.open():
        print("SIN ack -> revisa WiFi del Neo / DJI Fly cerrado."); sys.exit(1)
    print("hello -> ACK. Sesion abierta.")

    base = None
    for _ in range(10):
        w = s.poll(0.1)
        if w: base = w; break
    print("ventana RX type-5 baseline:", "0x%04x" % base[0] if base else "?")

    f = Flight(s, args.lat, args.lon)

    if not real:
        run_common(f, args)
        win = f.stream(args.hover, NEUTRAL, mode=True, hb=True,
                       label="3) DRY: heartbeat 0x03/0xd7 + NEUTRO (NO despega)...")
        print("ventana RX final:", "0x%04x" % win[0] if win else "?")
        if base and win:
            print(">>> %s" % ("VENTANA AVANZO (0x%04x->0x%04x): el dron ACEPTA la secuencia completa "
                  "(salvo despegue). Listo para --fly EXTERIOR." % (base[0], win[0])
                  if win[0] != base[0] else "ventana NO avanzo: revisar transporte."))
        s.sock.close(); return

    # ---- VUELO REAL ----
    print("\n" + "!" * 64)
    print(" VUELO REAL. EXTERIOR + SUPERVISADO + failsafe=Aterrizar.")
    print(" Ctrl+C = ATERRIZAR. Corte real = BOTON del dron.")
    print("!" * 64, flush=True)
    try:
        run_common(f, args)
        print(">>> DESPEGUE en 5 s (Ctrl+C aborta)...", flush=True)
        for i in range(5, 0, -1):
            print("   ", i, flush=True); time.sleep(1.0)
        f.stream(args.tkhold, NEUTRAL, mode=True, takeoff_hold=True,
                 label="4) DESPEGUE: manteniendo 0x03/0xda ~%.0fs (como el boton)..." % args.tkhold)
        wtk = f.stream(args.hover, NEUTRAL, mode=True, hb=True,
                       label="5) HOVER: heartbeat 0x03/0xd7 + NEUTRO (modo Manual)")
        print("   ventana RX t5:", ("0x%04x" % wtk[0]) if wtk else "?",
              "(seq propio ~0x%04x)" % f.s.seq, flush=True)
        print(">>> ATERRIZANDO: throttle-min. Mira descender...", flush=True)
        f.stream(args.land, (1024, 1024, THR_MIN, 1024), hb=True, label="")
        print(">>> Fin. Si sigue en el aire: BOTON del dron o failsafe.", flush=True)
    except KeyboardInterrupt:
        print("\n!! ABORTO -> aterrizando (throttle-min)", flush=True)
        try:
            f.stream(args.land, (1024, 1024, THR_MIN, 1024), hb=True)
        except KeyboardInterrupt:
            print("Saliendo. Failsafe=Aterrizar deberia bajarlo; si no, BOTON del dron.")
    finally:
        s.sock.close()
    print("FIN del vuelo.")

if __name__ == "__main__":
    main()
