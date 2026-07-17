"""Corre sysid_yaw.run() COMPLETO contra un Neo falso: sesion y OSD simulados.
Ejercita climb() + sysid_loop() + guardas + descend() sin dron. Acelera el tiempo."""
import sys, os, time, types
sys.path.insert(0, r"C:\Users\santi\Desktop\DJI project\tools\neo_control")
sys.argv = ["x"]
import neo_udp as N
import flight as F
import sysid_yaw as S

# ---- planta simulada: rate = k(|u|-d)sgn(u) con 1er orden tau; angulo = integral
K, D, TAU = 0.034, 75.0, 0.35
sim = {"t0": time.time(), "last": time.time(), "rate": 0.0, "ang": 0.0,
       "u": 0, "thr": 0, "h": 0.0, "motor": False, "nxt": 0.0}
last_cmd = {"r": 1024, "p": 1024, "th": 1024, "y": 1024}


def advance():
    now = time.time()
    dt = min(now - sim["last"], 0.05)
    sim["last"] = now
    u = last_cmd["y"] - 1024
    sp = K * max(0.0, abs(u) - D) * (1 if u > 0 else -1)
    sim["rate"] += (sp - sim["rate"]) * dt / TAU
    sim["ang"] += sim["rate"] * dt
    # altura: sube con throttle sobre el centro, altitude-hold si esta cerca de neutro
    if sim["motor"]:
        dthr = last_cmd["th"] - 1024
        if dthr <= -600:
            sim["h"] = max(0.0, sim["h"] - 0.4 * dt)
            if sim["h"] <= 0.02:
                sim["motor"] = False
        elif dthr > 300:
            sim["h"] += 0.25 * dt * (dthr / 450.0)
        else:
            sim["h"] = max(sim["h"], 0.7)      # auto-despegue se queda ~0.7


class FakeSock:
    def settimeout(self, t): pass
    def close(self): print("   [sim] socket cerrado")

    def recvfrom(self, n):
        advance()
        now = time.time()
        if now < sim["nxt"]:
            raise __import__("socket").timeout()
        sim["nxt"] = now + 0.1                 # OSD a 10 Hz, como el real
        return b"\x00", (N.DRONE[0], 9003)


class FakeSession:
    WINDOW = 48
    def __init__(self, hello=None):
        self.seed = 0x1234; self.session = 0xabcd; self.seq = 0
        self.sock = FakeSock(); self.sent = {}; self.drone_next = 0; self.n = 0
    def open(self): return True
    def send_command(self, mb): self.n += 1; return True
    def keepalive(self): pass
    def poll(self, timeout=0.05): return None


def fake_stick(self, r, p, th, y):
    last_cmd.update(r=r, p=p, th=th, y=y)
    return True


def fake_osd(pkt):
    w = ((sim["ang"] + 180) % 360) - 180
    return dict(flyc_state=6, on_ground=not sim["motor"], in_air=sim["motor"],
                motor_on=sim["motor"], usonic_on=True, mvo_used=True, batt_req_land=False,
                gps_used=False, gps_level=0, start_fail_reason=0, start_fail_happened=False,
                height_m=round(sim["h"], 1), vgx=0.0, vgy=0.0, vgz=0.0,
                pitch=0.0, roll=0.0, yaw=round(w, 1))


def fake_auto_fly(self):
    sim["motor"] = True
    print("   [sim] AUTO_FLY -> motores ON")
    return True


N.Type5Session = FakeSession
N.find_osd_general = fake_osd
N.find_battery_dynamic = lambda p: None
F.Flight.stick = fake_stick
F.Flight.auto_fly = fake_auto_fly
F.run_common = lambda f, a: print("   [sim] run_common (init+engage) saltado")


class A: pass
a = A()
a.fly = True; a.armed_ok = True; a.lat = None; a.lon = None
a.settle = 0.2; a.settle_air = 1.0; a.land = 6.0
a.alt = 1.5; a.alt_max = 3.5; a.climb_thr = 450.0; a.climb_secs = 2.0; a.climb_max = 6.0
a.step_levels = "100,200,300,400,500,660"; a.step_secs = 1.0
a.prbs_bits = 20; a.prbs_bit_secs = 0.3; a.prbs_bias = 0; a.prbs_amp = 660
a.out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fake.csv")

t0 = time.time()
S.run(a)
print("\n=== simulacion terminada en %.1f s reales ===" % (time.time() - t0))

import csv
with open(a.out, encoding="utf-8") as fh:
    rows = list(csv.DictReader([l for l in fh if not l.startswith("#")]))
print("muestras: %d" % len(rows))
phases = []
for r in rows:
    if not phases or phases[-1] != r["phase"]:
        phases.append(r["phase"])
print("fases recorridas: %s" % " -> ".join(phases))
us = [int(r["u_cmd"]) for r in rows]
print("u: min=%d max=%d  | ch3: %d..%d" % (min(us), max(us), 1024 + min(us), 1024 + max(us)))
yw = [float(r["yaw_unwrap_deg"]) for r in rows]
print("yaw des-envuelto: %.1f .. %.1f  (deriva final %.1f deg)" % (min(yw), max(yw), yw[-1]))
raw = [float(r["yaw_deg"]) for r in rows]
print("yaw crudo en +-180: %s" % ("SI" if all(-180 <= v <= 180 for v in raw) else "NO !!"))
dt = [float(rows[i + 1]["t_s"]) - float(rows[i]["t_s"]) for i in range(len(rows) - 1)]
print("dt real: min=%.3f p50=%.3f max=%.3f" % (min(dt), sorted(dt)[len(dt) // 2], max(dt)))
