r"""
gimbal_pid.py — LAZO DE VELOCIDAD del gimbal con el PID del usuario (EXP-038). EN TIERRA.

QUE PRUEBA ESTO
  El usuario ajusto su PID sobre G_rate (la planta rate_cmd -> rate, hoja
  'datos_prbs_rate'), que NO tiene integrador. Luego su PID controla la VELOCIDAD de la
  camara, no su angulo. Esta herramienta lo prueba TAL CUAL, sin cambiarle nada:
  se comanda un perfil de velocidad (+10 deg/s, -10, +20, ...) y el PID lo sigue.

  Valida DOS cosas a la vez:
    1. Su PID: ¿sigue la velocidad pedida?
    2. Mi inversion de zona muerta+expo: si esta bien, pedir 10 deg/s da 10 deg/s.
       (La ganancia DC de SU modelo salio 0.9658 ~ 1, que ya lo sugiere.)

  NO apunta la camara a un angulo: para eso hace falta tunear sobre G_rate*integrador.
  Pero un lazo de VELOCIDAD es util por si mismo para mapear: barridos a velocidad
  constante = video suave = mejor tracking de features para el SLAM.

GANANCIAS (del usuario, sobre su G_rate; NO se tocan):
    Kp = 0.395252998225006   Ki = 1.61924911918927   Kd = 0.0241199656610089
  UNIDADES: entrada = error de velocidad [deg/s]; salida = comando de velocidad [deg/s].
  La I aqui SI hace falta: G_rate no integra (ganancia DC 0.97), asi que sin I habria
  error estacionario. Es lo contrario que en el lazo de ANGULO (ahi la planta ya integra
  y la I sobra; ver EXP-036).

LA CADENA:
    rate_sp --(+)--> [PID] --> rate_cmd [deg/s] --> [sat +-26.2] --> [inversion expo]
                 -              --> stick 363..1685 --> gimbal --> gpitch
                 |                                                     |
                 +------------------ rate_med = d(gpitch)/dt <---------+

  rate_med se DERIVA de gpitch (el dron no reporta velocidad angular): diferencia HACIA
  ATRAS, causal, la MISMA con la que se genero 'datos_prbs_rate' -> el PID ve exactamente
  la señal para la que se ajusto. NADA de np.gradient (central = mira al futuro; ese bug
  hacia que el modelo saliera con menos retardo del real).

PLANTA (EXP-037): zona muerta 50 + expo 1.704, fondo 26.2 deg/s, tau=0.2 s, Ts=100 ms
(impuesto por el Push Position 0x04/0x05 a 9.90 Hz). Topes -90..+60 (nuestro path los
alcanza: la FASE A de EXP-037 llego a -89.9 y +56).

USO
  --sim                      simula contra la planta de EXP-037. Correr SIEMPRE antes.
  .\neo.ps1 gimbal_pid.py    prueba real EN TIERRA (no despega: 0x04/0x01 va al gimbal)
Ctrl+C = para y centra.
"""
import argparse, csv, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import neo_udp as N
import flight as F
from sysid_gimbal import (Gimbal, goto, clamp, TS, MAX_CMD,
                          rate_of, cmd_for_rate, DEADZONE_FIT, EXPO_A_FIT, EXPO_N_FIT)

# --- ganancias del usuario. NO TOCAR: son las que ajusto sobre SU G_rate. ---
KP, KI, KD = 0.395252998225006, 1.61924911918927, 0.0241199656610089

RATE_MAX = 26.2          # fondo de escala medido (EXP-037). Saturacion del PID.
LO_DEF, HI_DEF = -90.0, 60.0

# --- SU planta G_rate (para --sim), tal cual la ajusto ---
G_NUM = 0.204062259777642
G_DEN = [1.0, -1.383939517588334, 0.757955032569873, -0.162721328529897]


class RatePID:
    """PID discreto paralelo sobre el ERROR DE VELOCIDAD. Anti-windup por integracion
    condicional + back-calculation. Derivada sobre la MEDIDA (evita la patada al cambiar
    el setpoint); la medida ya es ruidosa (derivar 0.1 deg a 10 Hz da ~1 deg/s), pero
    Kd=0.024 la escala a ~0.24 deg/s sobre 26.2 => despreciable, como en el yaw."""

    def __init__(self, kp=KP, ki=KI, kd=KD, umax=RATE_MAX):
        self.kp, self.ki, self.kd, self.umax = kp, ki, kd, umax
        self.I = 0.0
        self.y_prev = None
        self.sat = False

    def step(self, sp, y, dt):
        e = sp - y
        P = self.kp * e
        D = 0.0 if self.y_prev is None else -self.kd * (y - self.y_prev) / dt
        self.y_prev = y
        u_un = P + self.I + D
        # no integres si ya saturas y el error empuja MAS hacia esa saturacion
        if not (abs(u_un) > self.umax and (u_un > 0) == (e > 0)):
            self.I += self.ki * dt * e
        u = P + self.I + D
        if abs(u) > self.umax:
            self.sat = True
            room = self.umax * (1 if u > 0 else -1) - (P + D)
            if (self.I > 0) == (room > 0) and abs(self.I) > abs(room):
                self.I = room
            u = clamp(P + self.I + D, -self.umax, self.umax)
        else:
            self.sat = False
        return u, e, P, self.I, D


def build_profile(args):
    """Perfil de velocidad (deg/s, segundos). SIMETRICO: cada tramo y su opuesto => el
    angulo vuelve ~al centro.

    La DURACION de cada tramo se dimensiona al RECORRIDO: un lazo de velocidad mueve el
    angulo sin parar (excursion = rate*secs), y el gimbal tiene topes. A 20 deg/s, 4 s son
    80 deg y solo hay ~67 utiles desde el centro => se estamparia. Se recorta a lo que
    cabe. (El sim SIN topes decia gpitch=73.6 con topes en +60: mentia.)"""
    room = (args.hi - args.lo) / 2.0 - args.margin
    prof = [(0.0, 2.0)]
    for r in (args.r1, args.r2, args.r3):
        if r <= 0:
            continue
        secs = min(args.hold, room / r)          # excursion = r*secs <= room
        if secs < 1.0:                            # menos de 1 s no da ni para el transitorio
            print("   (aviso: %+g deg/s no cabe en el recorrido, saltado)" % r)
            continue
        prof.append((+r, secs)); prof.append((-r, secs))
    prof.append((0.0, 2.0))
    return prof


# ------------------------------------------------------------------ simulacion
def simulate(args):
    """Lazo cerrado contra SU G_rate + la saturacion y la inversion reales."""
    pid = RatePID()
    prof = build_profile(args)
    yh = [0.0, 0.0, 0.0]        # historial de la salida de G_rate
    uh = [0.0, 0.0, 0.0]        # historial de su entrada
    ang = (args.lo + args.hi) / 2.0     # se arranca CENTRADO, como el vuelo real
    rows = []
    t = 0.0
    hits = 0
    print("SIM: SU G_rate (polos %s) + saturacion +-%.1f + inversion expo"
          % (", ".join("%.3f" % abs(x) for x in _roots(G_DEN)), RATE_MAX))
    print("     PID Kp=%.4f Ki=%.4f Kd=%.5f  Ts=%.0fms\n" % (KP, KI, KD, TS * 1000))
    for sp, secs in prof:
        n = int(secs / TS)
        errs = []
        for _ in range(n):
            y = yh[-1]                                   # velocidad medida
            # MISMA guarda de topes que el vuelo real, para que el sim no sea mas optimista
            sp_eff = sp
            if (sp > 0 and ang > args.hi - args.margin) or (sp < 0 and ang < args.lo + args.margin):
                sp_eff = -sp * 0.5
            u, e, P, I, D = pid.step(sp_eff, y, TS)
            # el comando pasa por saturacion -> inversion -> stick -> planta.
            # La inversion y la curva son inversas exactas, asi que en el sim el stick
            # reproduce u; lo que SI se aplica es el recorte del stick a +-660.
            stick = clamp(cmd_for_rate(u), -MAX_CMD, MAX_CMD)
            u_eff = rate_of(stick)
            uh.append(u_eff); uh.pop(0)
            # SU G_rate: y[k] = 1.3839 y[k-1] - 0.75796 y[k-2] + 0.16272 y[k-3] + 0.204 u[k-1]
            ynew = (-G_DEN[1] * yh[-1] - G_DEN[2] * yh[-2] - G_DEN[3] * yh[-3]
                    + G_NUM * uh[-2])
            yh.append(ynew); yh.pop(0)
            # TOPES MECANICOS: sin esto el sim miente (decia gpitch=73.6 con tope en +60)
            ang_new = ang + TS * ynew
            if ang_new > args.hi or ang_new < args.lo:
                hits += 1
                ang_new = clamp(ang_new, args.lo, args.hi)
            ang = ang_new
            t += TS
            errs.append(abs(e))
            rows.append((round(t, 2), sp, round(ynew, 3), round(u, 3),
                         round(stick, 1), round(ang, 2), int(pid.sat)))
        tail = errs[len(errs) // 2:]
        print("  sp=%+6.1f deg/s | rate final %+7.2f | |err| medio (2a mitad) %.3f | gpitch %+7.1f"
              % (sp, yh[-1], sum(tail) / len(tail), ang))
    sat = sum(r[6] for r in rows) / float(len(rows))
    print("\n  saturado el %.0f%% | gpitch recorrido %.1f .. %.1f  (topes %.0f/%.0f)"
          % (100 * sat, min(r[5] for r in rows), max(r[5] for r in rows), args.lo, args.hi))
    print("  choques contra el tope: %s"
          % ("%d muestras !! el perfil NO cabe" % hits if hits else "NINGUNO"))
    if args.sim_csv:
        with open(args.sim_csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["t", "rate_sp", "rate", "u_pid", "stick", "gpitch", "sat"])
            w.writerows(rows)
        print("  csv -> %s" % args.sim_csv)


def _roots(den):
    import cmath
    a, b, c, d = den
    # solo para imprimir: raices de un cubico por Durand-Kerner (sin numpy: corre en el
    # python del sistema, que no lo tiene)
    p = [complex(0.4, 0.9) ** i for i in range(3)]
    for _ in range(200):
        for i in range(3):
            num = ((p[i] ** 3) * a + (p[i] ** 2) * b + p[i] * c + d)
            den_ = 1.0
            for j in range(3):
                if i != j:
                    den_ *= (p[i] - p[j])
            p[i] = p[i] - num / den_
    return p


# ------------------------------------------------------------------ real
def run(args):
    prof = build_profile(args)
    total = sum(s for _, s in prof)
    print("=" * 70)
    print("  gimbal_pid.py — LAZO DE VELOCIDAD (EN TIERRA, no despega)")
    print("  PID del usuario TAL CUAL: Kp=%.4f Ki=%.4f Kd=%.5f" % (KP, KI, KD))
    print("  perfil: %s deg/s  |  sat +-%.1f deg/s  |  %.0fs"
          % ("/".join("%+g" % r for r, _ in prof if r), RATE_MAX, total))
    print("  Controla la VELOCIDAD, no el angulo (su G_rate no tiene integrador).")
    print("=" * 70)

    s = N.Type5Session()
    if not s.open():
        print("!! sin ACK al hello -> revisa WiFi del Neo."); return
    print("hello -> ACK.")
    f = F.Flight(s, None, None)
    gb = Gimbal(f)
    log = []
    args.t0 = time.time()
    pid = RatePID()
    try:
        for fr in F.INIT:
            f.s.send_command(fr); time.sleep(0.03)
        print(">>> ENGANCHE 0x51: %s" % ("OK" if f.engage() else "FALLO"), flush=True)
        if gb.wait_reading() is None:
            print("!! no llega el Push Position 0x04/0x05."); return
        center = (args.lo + args.hi) / 2.0
        print("centrando en %.1f deg..." % center, flush=True)
        goto(gb, center, args, [])

        g_prev, t_prev = gb.gp, time.time()
        u_hold = 0.0
        t0 = time.time()
        for sp, secs in prof:
            t_seg = time.time()
            print(">>> rate_sp = %+.1f deg/s  (%.1fs)" % (sp, secs), flush=True)
            nrep = 0.0
            while time.time() - t_seg < secs:
                stick = clamp(cmd_for_rate(u_hold), -MAX_CMD, MAX_CMD)
                g, tg = gb.pump(stick)
                if g is None:
                    continue
                dt = tg - t_prev
                if dt <= 0:
                    continue
                # velocidad medida: diferencia HACIA ATRAS (causal), la MISMA con la que
                # se ajusto el modelo. Nada de diferencia central.
                rate = (g - g_prev) / dt
                g_prev, t_prev = g, tg
                sp_eff = sp
                # guarda de topes: cerca de un limite, manda velocidad hacia el centro
                if (sp > 0 and g > args.hi - args.margin) or (sp < 0 and g < args.lo + args.margin):
                    sp_eff = -sp * 0.5
                u, e, P, I, D = pid.step(sp_eff, rate, dt)
                u_hold = u
                log.append(dict(t_s=round(tg - t0, 3), rate_sp=sp, rate_sp_eff=round(sp_eff, 2),
                                rate_med=round(rate, 3), u_pid=round(u, 3),
                                stick=round(stick, 1), gpitch=g, err=round(e, 3),
                                P=round(P, 3), I=round(I, 3), D=round(D, 3), sat=int(pid.sat)))
                if time.time() >= nrep:
                    print("   t+%5.1f sp=%+6.1f rate=%+7.2f err=%+6.2f u=%+6.2f stick=%+5.0f gp=%+6.1f%s"
                          % (tg - t0, sp_eff, rate, e, u, stick, g, " SAT" if pid.sat else ""),
                          flush=True)
                    nrep = time.time() + 0.7
        print("\ncentrando...", flush=True)
        goto(gb, center, args, [])
        gb.hold(0.5, 0)
    except KeyboardInterrupt:
        print("\n!! Ctrl+C -> parando", flush=True)
        try:
            gb.hold(0.5, 0)
        except Exception:
            pass
    finally:
        if s.sock:
            s.sock.close()

    if log:
        with open(args.out, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(log[0].keys()))
            w.writeheader(); w.writerows(log)
        print(">>> log: %d muestras -> %s" % (len(log), args.out))
        for sp, _ in prof:
            if sp == 0:
                continue
            seg = [r for r in log if r["rate_sp"] == sp]
            if len(seg) > 10:
                tail = seg[len(seg) // 2:]
                med = sum(r["rate_med"] for r in tail) / len(tail)
                print("   sp=%+6.1f -> rate medio (2a mitad) %+7.2f deg/s   error %+.2f"
                      % (sp, med, med - sp))


def main():
    ap = argparse.ArgumentParser(description="Lazo de velocidad del gimbal (EXP-038, en tierra)")
    ap.add_argument("--sim", action="store_true", help="simula contra SU G_rate. Correr antes")
    ap.add_argument("--sim-csv", dest="sim_csv", default=None)
    ap.add_argument("--r1", type=float, default=10.0, help="1er escalon de velocidad (deg/s)")
    ap.add_argument("--r2", type=float, default=20.0, help="2o escalon")
    ap.add_argument("--r3", type=float, default=5.0, help="3er escalon (lento: la zona dificil)")
    ap.add_argument("--hold", type=float, default=4.0, help="segundos por escalon")
    ap.add_argument("--lo", type=float, default=LO_DEF)
    ap.add_argument("--hi", type=float, default=HI_DEF)
    ap.add_argument("--margin", type=float, default=8.0)
    ap.add_argument("--out", default="gimbal_pid.csv")
    args = ap.parse_args()
    args.t0 = time.time()
    if args.sim:
        simulate(args); return
    run(args)


if __name__ == "__main__":
    main()
