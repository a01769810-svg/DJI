r"""
yaw_pid.py — LAZO CERRADO DE YAW con el PID diseñado por el usuario (EXP-035).

GANANCIAS (diseñadas por el usuario sobre la idtf ajustada a los datos de EXP-034):
    Kp = 121.251465320811   Ki = 95.1967343212135   Kd = 7.33540859003448   (sin filtro)
  UNIDADES: entrada = grados de error; salida = UNIDADES DE STICK (las mismas de
  'entrada_u' del Excel). Verificado: la ganancia de planta por minimos cuadrados sobre la
  curva estatica es 0.0683 deg/s por unidad de stick; Kp*0.0683 = 8.3 rad/s, del mismo
  orden que el cruce reportado (5.99 rad/s con el PID completo).

  => El PID escribe el stick DIRECTAMENTE. NO se aplica inversion de expo: la idtf se
     ajusto contra el stick CRUDO (el expo quedo promediado dentro del modelo lineal).
     Meter la inversion aqui cambiaria la planta para la que se diseño y las ganancias
     dejarian de valer.

ARQUITECTURA (EXP-034 + EXP-026):
  - El PID calcula a 10 Hz: lo limita la MEDIDA (el OSD 0x03/0x43 llega a 9.86 Hz).
  - El stick se retransmite a 20 Hz con retencion de orden cero: bajar el ritmo del
    stream rompe el enganche con el FC (deja de vernos como controlador activo).
  - Planta: yaw[k] = yaw[k-1] + Ts*rate[k-1], G(z) = Ts*z^-1/(1-z^-1). Integrador puro,
    sin retardo de transporte medible.

!! SATURACION — LO QUE MAS IMPORTA AQUI !!
  El stick satura en +-660 y el dron gira como mucho a ~49.5 deg/s. Con Kp=121.25, el
  termino P solo ya satura en cuanto |error| > 660/121.25 = 5.4 deg. Es decir:
    - Para un escalon de 90 deg el lazo va SATURADO (bang-bang) casi todo el giro y el
      tiempo lo fija el limite fisico: 90/49.5 = 1.8 s MINIMO. El 'rise time 0.3 s' del
      diseño lineal pediria 300 deg/s: IMPOSIBLE para este dron.
    - Las predicciones lineales (rise 0.3s, overshoot 9.33%, PM 86.4deg) SOLO valen en
      el ultimo tramo, con |error| < 5.4 deg. Fuera de ahi el lazo NO es lineal.
  Por eso el ANTI-WINDUP no es opcional: con Ki=95.2 integrando ~1.8 s de error grande,
  la integral se dispara y el dron se pasa de largo y oscila. Se usa integracion
  condicional (congelar la I mientras el mando este saturado y el error empuje al mismo
  lado) + back-calculation.

DERIVADA SOBRE LA MEDIDA, no sobre el error: con setpoints en escalon, D sobre el error
da una patada de Kd*90/Ts = 6600 unidades. No cambia estabilidad ni rechazo de
perturbacion, solo quita la patada. Ruido: el yaw esta cuantizado a 0.1 deg -> la
derivada mete +-1 deg/s -> *Kd = +-7 unidades de stick sobre 660 (~1%): despreciable,
por eso se puede ir sin filtro.

USO
  --sim                 simula el lazo contra la planta de EXP-034 (expo + integrador +
                        saturacion). SIN dron. Correr SIEMPRE antes de volar.
  .\neo.ps1 yaw_pid.py --fly --armed-ok    lazo cerrado real.
Ctrl+C = ATERRIZA.
"""
import argparse, csv, os, sys, time, socket

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import neo_udp as N
import flight as F

NEUTRAL = F.NEUTRAL
MAX_DEFL = 660          # rango real del stick: 364..1684, centro 1024 (flight.py:92)
TS = 0.1                # impuesto por el OSD (9.86 Hz). No se puede subir.

# --- ganancias del usuario (diseño en la idtf de EXP-034) ---
KP, KI, KD = 121.251465320811, 95.1967343212135, 7.33540859003448

# --- planta identificada en EXP-034 (para --sim) ---
EXPO_A, EXPO_N = 49.5, 1.351      # rate = A*(|u|/660)^N deg/s


def plant_rate(u):
    """Velocidad de giro estacionaria para un stick u. Curva EXPO medida (R2=0.9997)."""
    s = 1.0 if u >= 0 else -1.0
    return s * EXPO_A * (min(abs(u), MAX_DEFL) / float(MAX_DEFL)) ** EXPO_N


def wrap180(a):
    return ((a + 180.0) % 360.0) - 180.0


class YawPID:
    """PID discreto paralelo a Ts fijo, con anti-windup y derivada sobre la medida.
        u = Kp*e + Ki*Ts*sum(e) + Kd*(-(y[k]-y[k-1])/Ts)
    El error se calcula por el camino corto (wrap +-180): un setpoint a 179 con el dron
    en -179 son 2 grados, no 358."""

    def __init__(self, kp=KP, ki=KI, kd=KD, umax=MAX_DEFL, ts=TS):
        self.kp, self.ki, self.kd, self.umax, self.ts = kp, ki, kd, umax, ts
        self.I = 0.0
        self.y_prev = None
        self.sat = False

    def reset(self):
        self.I = 0.0; self.y_prev = None; self.sat = False

    def step(self, setpoint, y, dt=None):
        dt = dt or self.ts
        e = wrap180(setpoint - y)
        P = self.kp * e
        # D sobre la MEDIDA (sin patada al cambiar el setpoint); signo negativo
        if self.y_prev is None:
            D = 0.0
        else:
            dy = wrap180(y - self.y_prev)
            D = -self.kd * dy / dt
        self.y_prev = y
        # --- anti-windup: integracion CONDICIONAL. No integres si ya estas saturado y el
        # error empuja MAS hacia esa saturacion (si empuja de vuelta, si: hay que salir).
        u_un = P + self.I + D
        if not (abs(u_un) > self.umax and (u_un > 0) == (e > 0)):
            self.I += self.ki * dt * e
        u = P + self.I + D
        # back-calculation: recorta la I a lo justo para quedarse en el borde
        if abs(u) > self.umax:
            self.sat = True
            room = self.umax * (1 if u > 0 else -1) - (P + D)
            if (self.I > 0) == (room > 0) and abs(self.I) > abs(room):
                self.I = room
            u = max(-self.umax, min(self.umax, P + self.I + D))
        else:
            self.sat = False
        return u, e, P, self.I, D


def build_targets(args):
    """Lista de (grados_relativos, segundos_de_hold). Simetrica: vuelve al rumbo inicial."""
    a = args.angle
    return [(0.0, args.settle_air), (+a, args.hold), (-a, args.hold),
            (-a, args.hold), (+a, args.hold), (0.0, args.hold)]


# ------------------------------------------------------------------ simulacion
def simulate(args):
    """Lazo cerrado contra la planta de EXP-034: expo + integrador + 1 muestra de retardo
    + SATURACION. Sirve para ver el comportamiento REAL (no lineal) antes de volar."""
    pid = YawPID()
    tg = build_targets(args)
    yaw = 0.0
    sp_abs = 0.0
    rows = []
    t = 0.0
    # cola de retardo de UNA muestra: yaw[k] = yaw[k-1] + Ts*rate(u[k-1]), que es el
    # modelo medido en EXP-034 (G(z)=Ts*z^-1/(1-z^-1)). Con DOS elementos se estaria
    # simulando u[k-2] = el doble del retardo real.
    ud = [0.0]
    print("SIM: planta EXP-034 (expo %.1f/(x)^%.3f, sat +-%d, %d ms de retardo)"
          % (EXPO_A, EXPO_N, MAX_DEFL, TS * 1000))
    print("     PID Kp=%.2f Ki=%.2f Kd=%.3f  Ts=%.0fms" % (KP, KI, KD, TS * 1000))
    print()
    for rel, hold in tg:
        sp_abs = wrap180(sp_abs + rel)
        pid.I = pid.I                                  # (la I se conserva entre tramos)
        t_end = t + hold
        t_start = t
        reached = None
        while t < t_end:
            u, e, P, I, D = pid.step(sp_abs, yaw)
            ud.append(u); u_eff = ud.pop(0)            # 1 muestra de retardo
            yaw = wrap180(yaw + TS * plant_rate(u_eff))
            t += TS
            rows.append((round(t, 2), round(sp_abs, 2), round(yaw, 2), round(u, 1),
                         round(e, 2), round(P, 1), round(I, 1), round(D, 1), int(pid.sat)))
            if reached is None and abs(wrap180(sp_abs - yaw)) < 2.0:
                reached = t - t_start
        err = wrap180(sp_abs - yaw)
        print("  objetivo %+7.1f deg | yaw final %+7.1f | error %+5.2f deg | t_2deg=%s"
              % (sp_abs, yaw, err, ("%.1fs" % reached) if reached else "NO LLEGO"))
    # metricas de saturacion
    sat = sum(r[8] for r in rows) / float(len(rows))
    umax = max(abs(r[3]) for r in rows)
    imax = max(abs(r[6]) for r in rows)
    print()
    print("  saturado el %.0f%% del tiempo | |u| max=%.0f | |I| max=%.0f (sin anti-windup se dispararia)"
          % (100 * sat, umax, imax))
    if args.sim_csv:
        with open(args.sim_csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["t", "setpoint", "yaw", "u", "err", "P", "I", "D", "sat"])
            w.writerows(rows)
        print("  csv -> %s" % args.sim_csv)
    return rows


# ------------------------------------------------------------------ vuelo real
def pid_loop(f, args, log):
    """Lazo cerrado real. El PID recalcula SOLO al llegar OSD nuevo (~10Hz, es la medida);
    el stick se retransmite a 20Hz con el ultimo valor (ZOH) para no perder el enganche."""
    pid = YawPID()
    tg = build_targets(args)
    nt = {"stick": 0.0, "mode": 0.0, "auth": 0.0, "ka": 0.0, "sub": 0.0, "rep": 0.0}
    u_hold = 0.0
    t0 = time.time()
    # rumbo inicial: los objetivos son RELATIVOS a el (setpoint absoluto acumulado)
    o = None
    while o is None:
        o = _pump(f, nt, 0.0)
        if time.time() - t0 > 5:
            return "sin OSD"
    sp = o["yaw"]
    for rel, hold in tg:
        sp = wrap180(sp + rel)
        pid.y_prev = None
        t_seg = time.time()
        print(">>> objetivo: yaw = %+.1f deg  (%+.0f relativo, %.1fs)" % (sp, rel, hold), flush=True)
        while time.time() - t_seg < hold:
            o = _pump(f, nt, u_hold)
            if o is not None:                       # <- muestra nueva: recalcula el PID
                u, e, P, I, D = pid.step(sp, o["yaw"])
                u_hold = u
                log.append(dict(t_s=round(time.time() - t0, 3), setpoint=round(sp, 2),
                                yaw=o["yaw"], u=round(u, 1), err=round(e, 2),
                                P=round(P, 1), I=round(I, 1), D=round(D, 1),
                                sat=int(pid.sat), height_m=o["height_m"],
                                motor_on=int(o["motor_on"])))
                if o["height_m"] > args.alt_max:
                    print("!! altura %.1f > tope -> corto" % o["height_m"], flush=True)
                    return "alt"
                if not o["motor_on"] and time.time() - t0 > 5:
                    return "motores off"
                now = time.time()
                if now >= nt["rep"]:
                    print("  t+%5.1f sp=%+7.1f yaw=%+7.1f err=%+6.2f u=%+5.0f%s alt=%.1f"
                          % (now - t0, sp, o["yaw"], e, u, " SAT" if pid.sat else "    ",
                             o["height_m"]), flush=True)
                    nt["rep"] = now + 0.5
    return "plan"


def _pump(f, nt, u_hold):
    """Mantiene las pistas (sticks 20Hz con ZOH, modo, autoridad, keepalive, suscripcion)
    y devuelve el OSD si llego uno nuevo, o None."""
    now = time.time()
    if f.serial and now >= nt["sub"]:
        f.sub13(); nt["sub"] = now + 0.2
    if now >= nt["mode"]:
        f.set_mode(); nt["mode"] = now + 0.1
    if now >= nt["stick"]:
        y = int(round(max(-MAX_DEFL, min(MAX_DEFL, u_hold))))
        f.stick(1024, 1024, 1024, 1024 + y); nt["stick"] = now + 0.05    # 20 Hz, ZOH
    if now >= nt["auth"]:
        f.authority(); nt["auth"] = now + 1.0
    if now >= nt["ka"]:
        f.s.keepalive(); nt["ka"] = now + 0.5
    f.s.sock.settimeout(0.02)
    try:
        d, a = f.s.sock.recvfrom(65535)
    except (socket.timeout, BlockingIOError):
        return None
    if not (d and a[0] == N.DRONE[0]):
        return None
    b = N.find_battery_dynamic(d)
    if b: f.last_batt = b
    return N.find_osd_general(d)


def climb(f, args):
    """Ascenso validado en EXP-033 (empuje fuerte y sostenido, solo tras estabilizar)."""
    d_thr = max(0, min(int(args.climb_thr), 640))
    nt = {"stick": 0.0, "mode": 0.0, "auth": 0.0, "ka": 0.0, "sub": 0.0, "rep": 0.0}
    t0 = time.time(); push = None; osd = None
    while True:
        now = time.time(); t = now - t0
        h = osd["height_m"] if osd else 0.0
        if h >= 0.3 and push is None: push = now
        pushed = (now - push) if push else 0.0
        if (push and pushed >= args.climb_secs) or h >= args.alt or t > args.climb_max:
            print(">>> ascenso fin: alt=%.1fm (empuje %.1fs)" % (h, pushed), flush=True)
            return
        if f.serial and now >= nt["sub"]:
            f.sub13(); nt["sub"] = now + 0.2
        if now >= nt["mode"]:
            f.set_mode(); nt["mode"] = now + 0.1
        if now >= nt["stick"]:
            f.stick(1024, 1024, 1024 + (d_thr if h >= 0.3 else 0), 1024); nt["stick"] = now + 0.05
        if now >= nt["auth"]:
            f.authority(); nt["auth"] = now + 1.0
        if now >= nt["ka"]:
            f.s.keepalive(); nt["ka"] = now + 0.5
        f.s.sock.settimeout(0.03)
        try:
            d, a = f.s.sock.recvfrom(65535)
        except (socket.timeout, BlockingIOError):
            d = None
        if d and a[0] == N.DRONE[0]:
            o = N.find_osd_general(d)
            if o: osd = o
        if now >= nt["rep"]:
            print("  t+%5.1f [CLIMB] alt=%.1fm" % (t, h), flush=True); nt["rep"] = now + 1.0


def run(args):
    real = args.fly and args.armed_ok
    print("=" * 68)
    print("  yaw_pid.py — %s" % ("LAZO CERRADO REAL" if real else "DRY (no despega)"))
    print("  Kp=%.3f  Ki=%.3f  Kd=%.5f  (sin filtro)  Ts=%.0fms" % (KP, KI, KD, TS * 1000))
    print("  objetivos: %+.0f deg ida/vuelta x2  |  satura si |err| > %.1f deg"
          % (args.angle, MAX_DEFL / KP))
    print("=" * 68)
    if args.fly and not args.armed_ok:
        print("!! --fly requiere --armed-ok."); return
    if real:
        print("\n" + "!" * 68)
        print(" LAZO CERRADO. El dron gira SOLO buscando el rumbo. Espacio libre.")
        print(" Ctrl+C = ATERRIZAR.")
        print("!" * 68 + "\n")

    log = []
    reason = "?"
    s = N.Type5Session()
    if not s.open():
        print("!! sin ACK al hello -> revisa WiFi del Neo."); return
    print("hello -> ACK. Sesion abierta.")
    f = F.Flight(s, args.lat, args.lon)
    try:
        F.run_common(f, args)
        if real:
            print("3) DESPEGUE (AUTO_FLY)...", flush=True)
            f.auto_fly()
            climb(f, args)
        print("4) LAZO CERRADO...", flush=True)
        reason = pid_loop(f, args, log)
        print(">>> fin (%s)" % reason, flush=True)
    except KeyboardInterrupt:
        print("\n!! Ctrl+C -> ATERRIZANDO", flush=True); reason = "ctrl-c"
    finally:
        if real:
            print("5) ATERRIZAJE (throttle-min)...", flush=True)
            try:
                ok = f.descend(args.land)
                print(">>> touchdown %s" % ("CONFIRMADO" if ok else "NO confirmado"), flush=True)
            except KeyboardInterrupt:
                print("!! Ctrl+C en el aterrizaje. Si sigue arriba: boton del dron.", flush=True)
        if s.sock: s.sock.close()
    if log:
        with open(args.out, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(log[0].keys())); w.writeheader(); w.writerows(log)
        print(">>> log: %d muestras -> %s" % (len(log), args.out))
        errs = [abs(r["err"]) for r in log[-20:]]
        print(">>> |error| medio en las ultimas 20 muestras: %.2f deg" % (sum(errs) / len(errs)))


def main():
    ap = argparse.ArgumentParser(description="Lazo cerrado de yaw con PID (EXP-035)")
    ap.add_argument("--fly", action="store_true")
    ap.add_argument("--armed-ok", dest="armed_ok", action="store_true")
    ap.add_argument("--sim", action="store_true", help="simula contra la planta de EXP-034 (sin dron)")
    ap.add_argument("--sim-csv", dest="sim_csv", default=None)
    ap.add_argument("--angle", type=float, default=90.0, help="amplitud del escalon de yaw (deg)")
    ap.add_argument("--hold", type=float, default=6.0, help="segundos por objetivo")
    ap.add_argument("--settle-air", dest="settle_air", type=float, default=3.0)
    ap.add_argument("--out", default="yaw_pid.csv")
    ap.add_argument("--lat", type=float, default=None)
    ap.add_argument("--lon", type=float, default=None)
    ap.add_argument("--settle", type=float, default=4.0)
    ap.add_argument("--land", type=float, default=14.0)
    ap.add_argument("--alt", type=float, default=1.5)
    ap.add_argument("--alt-max", dest="alt_max", type=float, default=3.5)
    ap.add_argument("--climb-thr", dest="climb_thr", type=float, default=450.0)
    ap.add_argument("--climb-secs", dest="climb_secs", type=float, default=8.0)
    ap.add_argument("--climb-max", dest="climb_max", type=float, default=16.0)
    args = ap.parse_args()
    if args.sim:
        simulate(args); return
    run(args)


if __name__ == "__main__":
    main()
