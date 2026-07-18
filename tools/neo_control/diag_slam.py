#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
diag_slam.py — ¿este video es "SLAM-able"? Diagnostico previo, SIN instalar el stack pesado.

Responde en minutos la pregunta del CLAUDE.md: ¿el video tiene textura y MOVIMIENTO (paralaje)
suficientes para que un SLAM monocular lo procese? Mide, sobre el video ya grabado:

  1. INFO      resolucion, frames decodificados, fps/duracion aprox.
  2. CALIDAD   nitidez (varianza del Laplaciano), brillo, contraste, recorte de exposicion;
               descarta frames borrosos/corruptos (nuestro stream pierde paquetes).
  3. FEATURES  densidad de esquinas (ORB + Shi-Tomasi) y COBERTURA en rejilla (¿reparts.?).
  4. TRACKING  seguimiento Lucas-Kanade entre frames: cuantas se siguen y cuanto duran.
  5. PARALAJE  LO MAS IMPORTANTE: por cada par de frames con movimiento, ajusta HOMOGRAFIA
               (modela rotacion pura / plano) vs MATRIZ FUNDAMENTAL (permite traslacion 3D) y
               usa el score S_H/(S_H+S_F) estilo init de ORB-SLAM. Alto -> rotacion/plano (SIN
               paralaje, malo para inicializar). Bajo -> hay traslacion (paralaje, bueno).

No necesita calibracion (usa la fundamental, no calibrada). Da un VEREDICTO legible + consejo.

USO (python del .venv, que tiene cv2):
  .\.venv\Scripts\python tools\neo_control\diag_slam.py --video captures\mapflight_2026-07-18_2m.h265
Opciones: --every N (1 de cada N frames, def 2), --max-frames N, --clahe (realza contraste),
          --min-sharp F (umbral de nitidez; def auto), --save-dir DIR (vuelca frames anotados).
"""
import argparse
import os
import numpy as np
import cv2

ROT_THRESH = 0.45      # S_H/(S_H+S_F) > esto => par dominado por rotacion/plano (init de ORB-SLAM)
FLOW_STATIC = 1.0      # px: flujo mediano por debajo => sin movimiento real (frame ~estatico)
GRID = 8               # rejilla GxG para medir cobertura espacial de features


def stats_line(name, arr, unit="", fmt="%.1f"):
    a = np.asarray(arr, float)
    if a.size == 0:
        print("  %-14s sin datos" % name); return
    print(("  %-14s med " + fmt + " %s | p10 " + fmt + " | p90 " + fmt + " | min " + fmt + " | max " + fmt)
          % (name, np.median(a), unit, np.percentile(a, 10), np.percentile(a, 90), a.min(), a.max()))


def main():
    ap = argparse.ArgumentParser(description="Diagnostico SLAM (features + paralaje) de un video")
    ap.add_argument("--video", required=True, help="ruta al .h265/.mp4")
    ap.add_argument("--every", type=int, default=2, help="usa 1 de cada N frames (def 2)")
    ap.add_argument("--max-frames", dest="maxf", type=int, default=0, help="tope de frames a procesar (0=todos)")
    ap.add_argument("--clahe", action="store_true", help="realza contraste (CLAHE) antes de detectar")
    ap.add_argument("--min-sharp", dest="min_sharp", type=float, default=-1.0,
                    help="umbral de nitidez (Laplacian var); -1 = automatico (percentil 25)")
    ap.add_argument("--save-dir", dest="save_dir", default=None, help="volcar algunos frames anotados")
    a = ap.parse_args()

    cap = cv2.VideoCapture(a.video)
    if not cap.isOpened():
        raise SystemExit("no pude abrir: %s" % a.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    orb = cv2.ORB_create(nfeatures=1000)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)) if a.clahe else None
    lk = dict(winSize=(21, 21), maxLevel=3,
              criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))

    # --- PASO 1: decodificar + calidad de cada frame ---
    grays, sharp, bright, contrast, clip = [], [], [], [], []
    i = 0
    while True:
        r, fr = cap.read()
        if not r:
            break
        if i % a.every == 0:
            g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
            sharp.append(cv2.Laplacian(g, cv2.CV_64F).var())
            bright.append(float(g.mean()))
            contrast.append(float(g.std()))
            clip.append(float(((g < 4) | (g > 251)).mean()) * 100.0)  # % pixeles pegados a 0/255
            if clahe is not None:
                g = clahe.apply(g)
            grays.append(g)
        i += 1
        if a.maxf and len(grays) >= a.maxf:
            break
    cap.release()
    total_dec = i
    n = len(grays)
    if n < 5:
        raise SystemExit("solo %d frames utiles: video vacio o no decodifica." % n)

    dur = total_dec / fps if fps else 0.0
    print("=" * 70)
    print("  DIAGNOSTICO SLAM  —  %s" % os.path.basename(a.video))
    print("=" * 70)
    print("[1] INFO")
    print("  resolucion %dx%d | frames decodificados %d | procesados %d (1 de cada %d)"
          % (W, H, total_dec, n, a.every))
    if fps:
        print("  fps~%.1f | duracion~%.1fs" % (fps, dur))

    # umbral de nitidez: descarta el cuartil mas borroso (frames corruptos del stream)
    min_sharp = a.min_sharp if a.min_sharp >= 0 else float(np.percentile(sharp, 25))
    good = [k for k in range(n) if sharp[k] >= min_sharp]
    print("\n[2] CALIDAD DE IMAGEN")
    stats_line("nitidez(Lap)", sharp, fmt="%.0f")
    stats_line("brillo(0-255)", bright)
    stats_line("contraste(std)", contrast)
    stats_line("recorte %", clip, unit="%", fmt="%.1f")
    print("  umbral nitidez=%.0f -> %d/%d frames NITIDOS (%.0f%%); el resto se descarta"
          % (min_sharp, len(good), n, 100.0 * len(good) / n))
    if np.median(bright) < 45:
        print("  ! ESCENA OSCURA (brillo mediano %.0f): sube luz -> mas y mejores features" % np.median(bright))

    # --- PASO 3: densidad y cobertura de features (sobre frames nitidos) ---
    orb_counts, shi_counts, coverage = [], [], []
    sample = good[:: max(1, len(good) // 200)]      # ~200 frames para esta parte
    for k in sample:
        g = grays[k]
        kps = orb.detect(g, None)
        orb_counts.append(len(kps))
        pts = cv2.goodFeaturesToTrack(g, maxCorners=1000, qualityLevel=0.01, minDistance=7)
        shi_counts.append(0 if pts is None else len(pts))
        cells = set()
        if pts is not None:
            for p in pts.reshape(-1, 2):
                cells.add((int(p[0] * GRID / W), int(p[1] * GRID / H)))
        coverage.append(100.0 * len(cells) / (GRID * GRID))
    print("\n[3] FEATURES (textura)")
    stats_line("ORB/frame", orb_counts, fmt="%.0f")
    stats_line("Shi-Tomasi", shi_counts, fmt="%.0f")
    stats_line("cobertura %", coverage, unit="%", fmt="%.0f")

    # --- PASO 4 y 5: tracking + PARALAJE entre frames nitidos consecutivos ---
    tracked, flow_med, rot_scores = [], [], []
    n_static = n_rot = n_trans = 0
    pairs = list(zip(good[:-1], good[1:]))
    for (ka, kb) in pairs:
        ga, gb = grays[ka], grays[kb]
        p0 = cv2.goodFeaturesToTrack(ga, maxCorners=600, qualityLevel=0.01, minDistance=7)
        if p0 is None or len(p0) < 20:
            continue
        p1, stt, _ = cv2.calcOpticalFlowPyrLK(ga, gb, p0, None, **lk)
        if p1 is None:
            continue
        m = stt.ravel() == 1
        a0, a1 = p0[m].reshape(-1, 2), p1[m].reshape(-1, 2)
        if len(a0) < 15:
            continue
        tracked.append(len(a0))
        fl = np.linalg.norm(a1 - a0, axis=1)
        fmed = float(np.median(fl))
        flow_med.append(fmed)
        if fmed < FLOW_STATIC:
            n_static += 1
            continue
        # modelo homografia (rotacion/plano) vs fundamental (traslacion 3D)
        Hh, mH = cv2.findHomography(a0, a1, cv2.RANSAC, 3.0)
        Ff, mF = cv2.findFundamentalMat(a0, a1, cv2.FM_RANSAC, 3.0, 0.99)
        sH = float(mH.sum()) if mH is not None else 0.0
        sF = float(mF.sum()) if mF is not None else 0.0
        if sH + sF < 1:
            continue
        rscore = sH / (sH + sF)          # ~1 rotacion/plano (sin paralaje); bajo = paralaje
        rot_scores.append(rscore)
        if rscore > ROT_THRESH:
            n_rot += 1
        else:
            n_trans += 1

    print("\n[4] TRACKING (Lucas-Kanade entre frames nitidos)")
    stats_line("seguidas/par", tracked, fmt="%.0f")
    stats_line("flujo px", flow_med, unit="px", fmt="%.1f")

    print("\n[5] PARALAJE (rotacion pura vs traslacion real)  <-- LO CRITICO")
    moving = n_rot + n_trans
    print("  pares con movimiento: %d | ESTATICOS: %d" % (moving, n_static))
    if moving:
        stats_line("score H/(H+F)", rot_scores, fmt="%.2f")
        print("  clasificacion de pares en movimiento:")
        print("    TRASLACION (paralaje, BUENO): %d  (%.0f%%)" % (n_trans, 100.0 * n_trans / moving))
        print("    ROTACION/PLANO (SIN paralaje): %d  (%.0f%%)" % (n_rot, 100.0 * n_rot / moving))

    # --- VEREDICTO ---
    med_orb = np.median(orb_counts) if orb_counts else 0
    med_cov = np.median(coverage) if coverage else 0
    med_track = np.median(tracked) if tracked else 0
    pct_trans = (100.0 * n_trans / moving) if moving else 0
    feat_ok = med_orb >= 150 and med_cov >= 40
    track_ok = med_track >= 60
    paralaje_ok = pct_trans >= 25 and moving >= 10

    print("\n" + "=" * 70)
    print("  VEREDICTO")
    print("=" * 70)
    print("  Textura/features : %s (ORB med %.0f, cobertura %.0f%%)"
          % ("OK" if feat_ok else "POBRE", med_orb, med_cov))
    print("  Seguimiento      : %s (med %.0f seguidas/par)"
          % ("OK" if track_ok else "POBRE", med_track))
    print("  PARALAJE         : %s (%.0f%% de pares con traslacion real)"
          % ("OK" if paralaje_ok else "INSUFICIENTE", pct_trans))
    print()
    if feat_ok and track_ok and paralaje_ok:
        print("  => SLAM-ABLE. Hay textura, seguimiento y paralaje. Siguiente: ORB-SLAM3 en")
        print("     Ubuntu 20.04 + ROS Noetic (VM del usuario), con la calibracion de intrinsecos.")
    else:
        print("  => AUN NO IDEAL. Ajustes recomendados:")
        if not paralaje_ok:
            print("     - MAS TRASLACION: el mapeo fue rotacion-dominante (rotar NO da profundidad).")
            print("       Sube --defl en mapflight y prioriza moverte de lado/adelante sobre girar.")
        if not feat_ok:
            print("     - MAS TEXTURA/LUZ: pega hojas/patrones en paredes blancas, sube iluminacion.")
        if not track_ok:
            print("     - Movimiento mas SUAVE y lento (menos blur), o mejor exposicion.")
    print()

    if a.save_dir:
        os.makedirs(a.save_dir, exist_ok=True)
        for j, k in enumerate(sample[:: max(1, len(sample) // 8)][:8]):
            g = grays[k]
            vis = cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)
            pts = cv2.goodFeaturesToTrack(g, 400, 0.01, 7)
            if pts is not None:
                for p in pts.reshape(-1, 2).astype(int):
                    cv2.circle(vis, tuple(p), 2, (0, 255, 0), -1)
            cv2.imwrite(os.path.join(a.save_dir, "feat_%02d.jpg" % j), vis, [cv2.IMWRITE_JPEG_QUALITY, 80])
        print("  frames anotados -> %s/" % a.save_dir)


if __name__ == "__main__":
    main()
