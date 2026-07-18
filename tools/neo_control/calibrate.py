#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
calibrate.py — calibra los INTRINSECOS de la camara del Neo con un checkerboard.

Estima la matriz K (fx, fy, cx, cy) y la distorsion (k1,k2,p1,p2,k3) con
cv2.calibrateCamera, a partir de imagenes o de un VIDEO donde se ve el tablero
generado por make_checkerboard.py (por defecto 9x6 ESQUINAS internas).

IMPORTANTE (EIS): el Neo aplica estabilizacion que NO se puede apagar. Por eso hay
que calibrar sobre EL MISMO tipo de video que se usara para mapear (misma resolucion
y modo). La K resultante absorbe el recorte/warp nominal del EIS. Estos intrinsecos
valen SOLO para ese modo de camara; si cambias resolucion/FOV, recalibra.

FLUJO DE CAPTURA sugerido (con video.py apuntando al tablero, tablero PLANO y rigido):
  15-25 vistas distintas: cerca/lejos, inclinado en las 4 direcciones, y que el tablero
  aparezca tambien en las ESQUINAS del cuadro (ahi vive la distorsion). Imagen NITIDA.

USO (con el python del .venv, que tiene cv2):
  .venv\\Scripts\\python tools\\neo_control\\calibrate.py --video capturas\\calib.h265 --square-mm 25.0
  .venv\\Scripts\\python tools\\neo_control\\calibrate.py --images data\\calibration\\shots --square-mm 24.3
Salidas: data/calibration/neo_intrinsics.json (+ .yaml estilo ORB-SLAM3) y, si --draw,
las detecciones dibujadas para revisar a ojo.
"""
import argparse, glob, json, os
import numpy as np
import cv2

IMG_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff")


def find_corners(gray, pattern):
    """Devuelve (ok, corners subpixel) probando el detector robusto SB y, si no, el clasico."""
    try:                                                    # SB: mas robusto (OpenCV >=4)
        ok, corners = cv2.findChessboardCornersSB(
            gray, pattern, flags=cv2.CALIB_CB_EXHAUSTIVE | cv2.CALIB_CB_ACCURACY)
        if ok:
            return True, corners
    except Exception:
        pass
    ok, corners = cv2.findChessboardCorners(
        gray, pattern, flags=cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE)
    if ok:
        crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
        corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), crit)
    return ok, corners


def sharpness(gray):
    """Varianza del Laplaciano: proxy de nitidez, para descartar fotogramas borrosos."""
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def load_frames(args):
    """Genera (nombre, imagen_bgr) desde --images o --video (muestreando 1 de cada --every)."""
    if args.images:
        files = sorted(f for f in glob.glob(os.path.join(args.images, "*"))
                       if f.lower().endswith(IMG_EXT))
        for f in files:
            img = cv2.imread(f)
            if img is not None:
                yield os.path.basename(f), img
    else:
        cap = cv2.VideoCapture(args.video)
        if not cap.isOpened():
            raise SystemExit("no pude abrir el video: %s" % args.video)
        i = 0
        while True:
            ok, fr = cap.read()
            if not ok:
                break
            if i % args.every == 0:
                yield "frame_%06d" % i, fr
            i += 1
        cap.release()


def main():
    ap = argparse.ArgumentParser(description="Calibracion de intrinsecos con checkerboard")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--images", help="carpeta con imagenes del tablero")
    src.add_argument("--video", help="video (.h265/.mp4/...) con el tablero")
    ap.add_argument("--cols", type=int, default=9, help="ESQUINAS internas a lo ancho (10 cuadros -> 9)")
    ap.add_argument("--rows", type=int, default=6, help="ESQUINAS internas a lo alto (7 cuadros -> 6)")
    ap.add_argument("--square-mm", dest="sq", type=float, default=25.0,
                    help="lado REAL del cuadro impreso en mm (MIDELO tras imprimir)")
    ap.add_argument("--every", type=int, default=15, help="con --video: usa 1 de cada N fotogramas")
    ap.add_argument("--min-sharpness", dest="min_sharp", type=float, default=0.0,
                    help="descarta fotogramas con nitidez < umbral (0 = no filtrar)")
    ap.add_argument("--draw", default=None, help="carpeta donde volcar las detecciones dibujadas")
    ap.add_argument("--out", default=None, help="ruta base de salida (sin extension)")
    a = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    out_base = a.out or os.path.abspath(os.path.join(here, "..", "..", "data", "calibration", "neo_intrinsics"))
    os.makedirs(os.path.dirname(out_base), exist_ok=True)
    if a.draw:
        os.makedirs(a.draw, exist_ok=True)

    pattern = (a.cols, a.rows)
    # rejilla 3D del tablero (z=0), en mm -> los intrinsecos salen en px y la escala en mm
    objp = np.zeros((a.rows * a.cols, 3), np.float32)
    objp[:, :2] = np.mgrid[0:a.cols, 0:a.rows].T.reshape(-1, 2) * a.sq

    objpoints, imgpoints, used = [], [], []
    imsize = None
    scanned = found = 0
    for name, img in load_frames(a):
        scanned += 1
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if imsize is None:
            imsize = (gray.shape[1], gray.shape[0])          # (w, h)
        elif (gray.shape[1], gray.shape[0]) != imsize:
            print("  ! %s tiene otra resolucion %s (esperaba %s), lo salto"
                  % (name, (gray.shape[1], gray.shape[0]), imsize))
            continue
        if a.min_sharp and sharpness(gray) < a.min_sharp:
            continue
        ok, corners = find_corners(gray, pattern)
        if not ok:
            continue
        found += 1
        objpoints.append(objp.copy())
        imgpoints.append(corners)
        used.append(name)
        if a.draw:
            vis = img.copy()
            cv2.drawChessboardCorners(vis, pattern, corners, True)
            cv2.imwrite(os.path.join(a.draw, name + ".jpg"), vis, [cv2.IMWRITE_JPEG_QUALITY, 85])

    print("fotogramas revisados=%d, tablero detectado=%d" % (scanned, found))
    if found < 6:
        raise SystemExit("MUY POCAS vistas (%d). Necesito >=8-10 buenas y variadas. "
                         "Revisa nitidez, que el tablero este plano y bien iluminado." % found)
    if found < 10:
        print("  ! solo %d vistas: la calibracion sera pobre. Idealmente 15-25 variadas." % found)

    rms, K, dist, rvecs, tvecs = cv2.calibrateCamera(objpoints, imgpoints, imsize, None, None)

    # error de reproyeccion por vista -> para cazar tomas malas
    per_view = []
    for i in range(len(objpoints)):
        proj, _ = cv2.projectPoints(objpoints[i], rvecs[i], tvecs[i], K, dist)
        e = cv2.norm(imgpoints[i], proj, cv2.NORM_L2) / len(proj)
        per_view.append((e, used[i]))
    per_view.sort(reverse=True)

    w, h = imsize
    fx, fy, cx, cy = K[0, 0], K[1, 1], K[0, 2], K[1, 2]
    fov_x = np.degrees(2 * np.arctan(w / (2 * fx)))
    fov_y = np.degrees(2 * np.arctan(h / (2 * fy)))
    d = dist.ravel().tolist()
    while len(d) < 5:
        d.append(0.0)

    print("\n=== RESULTADO ===")
    print("resolucion   : %d x %d" % (w, h))
    print("RMS reproy.  : %.4f px   (%s)" % (rms, "excelente <0.5" if rms < 0.5 else
                                             "aceptable <1.0" if rms < 1.0 else "ALTO >1.0, revisa tomas"))
    print("fx, fy       : %.2f, %.2f px" % (fx, fy))
    print("cx, cy       : %.2f, %.2f px  (centro nominal %.1f, %.1f)" % (cx, cy, w / 2, h / 2))
    print("FOV          : %.1f x %.1f deg" % (fov_x, fov_y))
    print("dist k1k2p1p2k3: [%s]" % ", ".join("%.5f" % v for v in d[:5]))
    print("peores vistas: " + ", ".join("%s=%.2f" % (n, e) for e, n in per_view[:3]))

    result = dict(image_width=w, image_height=h, fx=fx, fy=fy, cx=cx, cy=cy,
                  dist_k1=d[0], dist_k2=d[1], dist_p1=d[2], dist_p2=d[3], dist_k3=d[4],
                  rms_reproj_px=rms, fov_x_deg=fov_x, fov_y_deg=fov_y,
                  square_mm=a.sq, pattern_inner=[a.cols, a.rows], n_views=found)
    with open(out_base + ".json", "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)

    # YAML estilo ORB-SLAM3 (para el paso de SLAM en Ubuntu/ROS)
    yaml = ("%%YAML:1.0\n---\n# Neo intrinsics (calibrado sobre video CON EIS; valido solo para\n"
            "# este modo de camara). RMS=%.4f px, %d vistas, cuadro=%.2f mm.\n"
            "Camera.type: \"PinHole\"\n"
            "Camera.fx: %.6f\nCamera.fy: %.6f\nCamera.cx: %.6f\nCamera.cy: %.6f\n"
            "Camera.k1: %.6f\nCamera.k2: %.6f\nCamera.p1: %.6f\nCamera.p2: %.6f\nCamera.k3: %.6f\n"
            "Camera.width: %d\nCamera.height: %d\n"
            % (rms, found, a.sq, fx, fy, cx, cy, d[0], d[1], d[2], d[3], d[4], w, h))
    with open(out_base + ".yaml", "w", encoding="utf-8") as fh:
        fh.write(yaml)
    print("\nguardado: %s.json  y  %s.yaml" % (out_base, out_base))


if __name__ == "__main__":
    main()
