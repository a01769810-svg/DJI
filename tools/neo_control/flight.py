#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
flight.py — Vuelo del DJI Neo (EXP-024). Wrapper UDP fiable (EXP-018) + envoltorio
0x51/0x01 (EXP-023) + DESPEGUE REAL via FunctionControl (EXP-024).

CORRECCION EXP-024: el despegue NO es 0x03/0xda (eso es Detection/housekeeping); es
FunctionControl 0x03/0x2a:01 AUTO_FLY, y el aterrizaje 0x03/0x2a:02 AUTO_LANDING,
ambos ENVUELTOS en 0x51/0x01. Confirmado: 0x03/0x2a:01 aparece solo en sesiones con
vuelo real, con ack DN=00 del dron.

Secuencia (validada byte a byte por analysis/validate_arm.py contra Quinta/Octava):
  HELLO -> reliable-UDP -> init (8 frames) -> modo Manual (envuelto) + NEUTRO + autoridad
        -> [--fly] AUTO_FLY (0x03/0x2a:01, envuelto) -> hover NEUTRO
        -> AUTO_LANDING (0x03/0x2a:02, envuelto)
  Opcional --detection-prep: manda el housekeeping Detection/params del arranque
  (0x03/0xf8, 0x03/0x34, 0x03/0x3c, 0x0d/0x03, 0x03/0xda). NO se asume precondicion.

MODOS:
  (sin flags)         DRY RUN: init + modo + NEUTRO + autoridad, SIN AUTO_FLY. Confirma
                      que el dron acepta la secuencia (ventana RX avanza). SEGURO interior.
  --fly --armed-ok    VUELO REAL: manda AUTO_FLY. REQUIERE los DOS flags + tecleo VOLAR.

Coordenada de autoridad var-03 (privacidad):
  --lat / --lon en grados decimales, en runtime, NO se guardan. Sin ellas => var-02.

SEGURIDAD (obligatoria para --fly):
  - GPS NO es requisito (el Neo vuela por vision/IR). SI lo es el sensor de abajo:
    dron PLANO sobre piso normal, no reflejante, sensores IR/vision despejados.
  - Area despejada SIN personas ni mascotas cerca (auto-despegue ~1.2 m). Supervisado.
  - Helices firmes. DJI Fly con failsafe = ATERRIZAR configurado de antemano.
  - Ctrl+C = AUTO_LANDING. Corte de emergencia real = BOTON del dron.

USO:
  python flight.py                                    # DRY RUN seguro (sin AUTO_FLY)
  python flight.py --fly --armed-ok                   # VUELO REAL (exterior/supervisado)
  python flight.py --fly --armed-ok --lat .. --lon .. # VUELO REAL con autoridad var-03
"""
import argparse, sys, time, threading
from datetime import datetime
import neo_udp as N


class KeepAlive:
    """Mantiene viva la sesion UDP fiable enviando el hello keepalive en un hilo de
    fondo durante PAUSAS (input del usuario, cuenta atras). Sin esto, un silencio de
    varios segundos hace que el dron DESCARTE la sesion (la ventana RX se congela en
    el seed) y todo comando posterior se ignora. Bug que invalidaba todos los --fly."""
    def __init__(self, sess, period=0.3):
        self.s = sess; self.period = period
        self._stop = threading.Event(); self._t = None
    def __enter__(self):
        def run():
            while not self._stop.wait(self.period):
                try:
                    self.s.keepalive()
                except Exception:
                    pass
        self._t = threading.Thread(target=run, daemon=True); self._t.start()
        return self
    def __exit__(self, *a):
        self._stop.set()
        if self._t:
            self._t.join(timeout=1.0)
        return False

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

NEUTRAL = (1024, 1024, 1024, 1024)     # roll,pitch,thr,yaw centrados => hover

def deg_to_e6(d):
    """grados decimales -> int32 grados*1e6 (formato de la autoridad var-03)."""
    return int(round(d * 1_000_000))

class Flight:
    def __init__(self, sess, lat=None, lon=None):
        self.s = sess
        self.dseq = 0xe600
        self.hb = 0                       # contador del heartbeat 0x03/0xd7 (opcional)
        self.hb_started = False
        self.wdseq = 1                    # contador del canal 0x51/0x01 (transmision transparente)
        # autoridad var-03 solo si hay coordenada; si no, var-02
        self.auth_state = 0x03 if (lat is not None and lon is not None) else 0x02
        self.lat_e6 = deg_to_e6(lat) if lat is not None else 0
        self.lon_e6 = deg_to_e6(lon) if lon is not None else 0

    def _dseq(self):
        v = self.dseq; self.dseq = (self.dseq + 1) & 0xffff; return v

    def _wrapped(self, inner):
        """Envia un frame DUML por el canal 0x51/0x01 (armado/commit/params van asi)."""
        r = self.s.send_command(N.wrap_5101(self.wdseq, inner))
        self.wdseq = (self.wdseq + 1) & 0xffffffff
        return r

    # -- BARE (crudos, como la app): sticks, autoridad, iniciar-despegue 05 --
    def stick(self, r, p, th, y):
        mb = N.mb_frame(0x02, 0xa9, self._dseq(), 0x00, 0x01, 0x0a,
                        b"\x01\x0d\x00" + _V(r, p, th, y) + b"\x40\x00\x02\x00\x00\x06\x55\x01\x04")
        return self.s.send_command(mb)

    def authority(self):
        # ts = timestamp Unix real (el contador de la autoridad es la hora en segundos)
        ts = int(time.time())
        return self.s.send_command(
            N.authority_frame(self._dseq(), ts, self.auth_state, self.lat_e6, self.lon_e6))

    # -- ENVUELTOS en 0x51/0x01 (como la app): DESPEGUE/ATERRIZAJE, modo, GETs --
    def auto_fly(self):
        """DESPEGUE REAL (EXP-024): FunctionControl 0x03/0x2a:01 AUTO_FLY, envuelto.
        El dron responde DN 0x03/0x2a=00 (ack)."""
        return self._wrapped(N.funcctrl_frame(self._dseq(), N.AUTO_FLY))

    def auto_landing(self):
        """ATERRIZAJE: FunctionControl 0x03/0x2a:02 AUTO_LANDING, envuelto."""
        return self._wrapped(N.funcctrl_frame(self._dseq(), N.AUTO_LANDING))

    def set_mode(self, mode=N.MODE_MANUAL):
        return self._wrapped(N.mode_frame(self._dseq(), mode))

    def detection_prep(self):
        """Housekeeping del arranque que la app manda antes del despegue (params +
        GETs + Detection). EXP-024: NO es takeoff ni se ha probado que sea precondicion
        obligatoria; opcional (--detection-prep). 0xda:05 va bare (como la app)."""
        self._wrapped(N.f8_frame(self._dseq()))
        self._wrapped(N.get_plane_name_frame(self._dseq()))
        self._wrapped(N.get_fs_action_frame(self._dseq()))
        self._wrapped(N.frame_0d03(self._dseq()))
        self.s.send_command(N.detection_setswitch_frame(self._dseq()))   # bare
        self._wrapped(N.detection_frame_0a(self._dseq()))
        n = datetime.now()
        self._wrapped(N.detection_frame_07(self._dseq(), n.year, n.month, n.day,
                                           n.hour, n.minute, n.second))
        self._wrapped(N.detection_frame_08(self._dseq()))

    def heartbeat(self):
        """0x03/0xd7 GetPushFlightRecord (suscripcion, housekeeping). Opcional."""
        if not self.hb_started:
            self.hb_started = True
            return self._wrapped(N.d7_frame(self._dseq(), 0, init=True))
        r = self._wrapped(N.d7_frame(self._dseq(), self.hb))
        self.hb = (self.hb + 1) & 0xffffffff
        return r

    def stream(self, secs, sticks=None, mode=False, auth=True, hb=False, label=""):
        """Streamea durante 'secs' varias 'pistas' a su frecuencia observada:
             sticks 20Hz · modo 10Hz · heartbeat d7 10Hz · autoridad 1Hz · keepalive 2Hz.
           Devuelve la ultima ventana RX type-5 del dron."""
        if label: print(label, flush=True)
        end = time.time() + secs
        nt = {"stick": 0.0, "mode": 0.0, "hb": 0.0, "auth": 0.0, "ka": 0.0}
        last_win = None
        while time.time() < end:
            now = time.time()
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
    """HELLO ya hecho. init minimo + modo Manual + settle NEUTRO + autoridad.
       Detection prep solo si --detection-prep (EXP-024: no probado como precondicion).
       Comun a DRY y a --fly. NO incluye el despegue (AUTO_FLY)."""
    print("enviando init (%d frames)..." % len(INIT))
    for fr in INIT:
        f.s.send_command(fr); time.sleep(0.03)
    f.stream(1.5, mode=True, auth=True, label="0) fijando MODO MANUAL + autoridad...")
    f.stream(args.settle, NEUTRAL, mode=True,
             label="1) settle: modo Manual + NEUTRO + autoridad var-0%d" % f.auth_state)
    if getattr(args, "detection_prep", False):
        print("2) Detection prep (0x03/0xf8 + GETs + 0x03/0xda). Opcional; NO despega.", flush=True)
        f.detection_prep()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fly", action="store_true", help="ejecutar VUELO REAL (motores)")
    ap.add_argument("--armed-ok", dest="armed_ok", action="store_true",
                    help="2do candado: confirma exterior+supervisado+failsafe")
    ap.add_argument("--lat", type=float, default=None, help="latitud grados (autoridad var-03)")
    ap.add_argument("--lon", type=float, default=None, help="longitud grados (autoridad var-03)")
    ap.add_argument("--settle", type=float, default=4.0)
    ap.add_argument("--hover", type=float, default=4.0)
    ap.add_argument("--land", type=float, default=12.0)
    ap.add_argument("--detection-prep", dest="detection_prep", action="store_true",
                    help="enviar el housekeeping Detection/params antes del despegue (opcional)")
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
        print("  autoridad en VAR-02 (coord en cero). GPS NO es requisito (EXP-024); el Neo")
        print("  vuela por vision/IR. --lat/--lon (VAR-03) es opcional, no cambia el armado.")
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
        win = f.stream(args.hover, NEUTRAL, mode=True,
                       label="3) DRY: modo + NEUTRO + autoridad (NO manda AUTO_FLY)...")
        print("ventana RX final:", "0x%04x" % win[0] if win else "?")
        if base and win:
            print(">>> %s" % ("VENTANA AVANZO (0x%04x->0x%04x): el dron ACEPTA la secuencia "
                  "(salvo AUTO_FLY). Listo para --fly (area despejada, piso normal)." % (base[0], win[0])
                  if win[0] != base[0] else "ventana NO avanzo: revisar transporte."))
        s.sock.close(); return

    # ---- VUELO REAL ----
    print("\n" + "!" * 64)
    print(" VUELO REAL. Area despejada (sin personas) + piso normal (sensor IR) + supervisado.")
    print(" Ctrl+C = ATERRIZAR (AUTO_LANDING). Corte real = BOTON del dron.")
    print("!" * 64, flush=True)
    try:
        run_common(f, args)
        # Confirmacion tecleada: AUTO_FLY despega de verdad. Freno anti-despegue-interior.
        # El prompt y la cuenta van dentro de KeepAlive para que la sesion NO muera en la
        # pausa (si no, la ventana RX se congela y el despegue se ignora).
        print("\n  El siguiente paso manda AUTO_FLY (0x03/0x2a:01): PUEDE despegar.")
        print("  Confirma: area despejada (sin personas), dron plano en piso normal (sensor IR).")
        with KeepAlive(s):
            try:
                confirmed = input("  Escribe VOLAR y Enter para despegar (cualquier otra cosa aborta): ").strip()
            except EOFError:
                confirmed = ""
            if confirmed != "VOLAR":
                print(">>> No confirmado / stdin no interactivo. Abortado sin despegar.")
                s.sock.close(); return
            print(">>> DESPEGUE en 5 s (Ctrl+C aborta)...", flush=True)
            for i in range(5, 0, -1):
                print("   ", i, flush=True); time.sleep(1.0)
        # re-sincroniza el streaming activo (drena downlink, reafirma modo) antes del comando
        rw = f.stream(1.0, NEUTRAL, mode=True, label="4) re-sync de sesion antes de AUTO_FLY...")
        print("   ventana RX pre-AUTO_FLY:", ("0x%04x" % rw[0]) if rw else "?", flush=True)
        print("4) AUTO_FLY (FunctionControl 0x03/0x2a:01, envuelto)...", flush=True)
        f.auto_fly()
        wtk = f.stream(args.hover, NEUTRAL, mode=True,
                       label="5) HOVER: NEUTRO (modo Manual) + autoridad")
        print("   ventana RX t5:", ("0x%04x" % wtk[0]) if wtk else "?",
              "(seq propio ~0x%04x)" % f.s.seq, flush=True)
        print("6) AUTO_LANDING (0x03/0x2a:02, envuelto). Mira descender...", flush=True)
        f.auto_landing()
        f.stream(args.land, NEUTRAL, mode=True, label="")
        print(">>> Fin. Si sigue en el aire: BOTON del dron o failsafe.", flush=True)
    except KeyboardInterrupt:
        print("\n!! ABORTO -> AUTO_LANDING", flush=True)
        try:
            f.auto_landing()
            f.stream(args.land, NEUTRAL, mode=True)
        except KeyboardInterrupt:
            print("Saliendo. Failsafe=Aterrizar deberia bajarlo; si no, BOTON del dron.")
    finally:
        s.sock.close()
    print("FIN del vuelo.")

if __name__ == "__main__":
    main()
