#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
slam_check.py — Diagnostico de "mapeabilidad" (SLAM) de un video del Neo, ANTES de montar
el stack pesado (ROS/ORB-SLAM3). Mide: densidad de features (ORB) por frame, seguimiento
frame-a-frame (optical flow) y el movimiento (proxy de PARALAJE). Requiere cv2 (usar el
python del .venv). USO:  .\\.venv\\Scripts\\python analysis\\slam_check.py <video.h265>
"""
import sys
import cv2
import numpy as np


def check(path, step=3):
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        print("no se pudo abrir:", path); return
    orb = cv2.ORB_create(3000)
    prev_gray = prev_pts = None
    feats = []; flows = []; tracked = []
    n = used = 0
    while True:
        r, fr = cap.read()
        if not r:
            break
        n += 1
        if n % step:
            continue
        gray = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        feats.append(len(orb.detect(gray, None)))
        pts = cv2.goodFeaturesToTrack(gray, 500, 0.01, 10)
        if prev_gray is not None and prev_pts is not None and len(prev_pts):
            nxt, sttus, _ = cv2.calcOpticalFlowPyrLK(prev_gray, gray, prev_pts, None)
            good = sttus.ravel() == 1
            if good.sum() > 5:
                d = np.linalg.norm((nxt[good] - prev_pts[good]).reshape(-1, 2), axis=1)
                flows.append(float(np.median(d))); tracked.append(float(good.mean()))
        prev_gray, prev_pts = gray, pts
        used += 1
    if not feats:
        print("no se decodifico ningun frame."); return

    feats = np.array(feats)
    lowtex = int((feats < 150).sum())
    print("=" * 60)
    print("DIAGNOSTICO SLAM:", path)
    print("frames analizados: %d (de %d, 1 de cada %d)" % (used, n, step))
    print("-- TEXTURA (features ORB por frame) --")
    print("   media=%.0f  mediana=%.0f  min=%d  max=%d" % (feats.mean(), np.median(feats), feats.min(), feats.max()))
    print("   frames con <150 features (textura pobre): %d (%.0f%%)" % (lowtex, 100 * lowtex / len(feats)))
    if flows:
        fl = np.array(flows); tr = np.array(tracked)
        print("-- PARALAJE / MOVIMIENTO (optical flow) --")
        print("   movimiento px/frame: media=%.1f  mediana=%.1f  (0=camara quieta)" % (fl.mean(), np.median(fl)))
        print("   seguimiento: %.0f%% de features rastreadas frame a frame" % (100 * tr.mean()))
        static = int((fl < 1.0).sum())
        print("   frames casi sin movimiento (<1px): %d (%.0f%%)" % (static, 100 * static / len(fl)))
    print("-- VEREDICTO --")
    ok_tex = feats.mean() >= 200 and lowtex < 0.4 * len(feats)
    ok_par = bool(flows) and np.mean(flows) >= 2.0 and np.mean(tracked) >= 0.4
    fast = bool(flows) and np.mean(flows) > 25.0
    if ok_tex and ok_par:
        print("   [OK] MAPEABLE: hay textura y paralaje suficientes para intentar SLAM.")
        if fast:
            print("   [nota] el movimiento fue RAPIDO (%.0f px/frame); en el vuelo real, mas"
                  " lento/suave da mejor SLAM (menos motion blur)." % np.mean(flows))
    else:
        if not ok_tex:
            print("   [!] TEXTURA justa: apunta a muebles/objetos, evita paredes lisas, mas luz.")
        if not ok_par:
            print("   [!] PARALAJE justo: mueve la camara TRASLADANDOLA (no solo girar).")
    print("=" * 60)


if __name__ == "__main__":
    check(sys.argv[1] if len(sys.argv) > 1 else "map_video.h265")
