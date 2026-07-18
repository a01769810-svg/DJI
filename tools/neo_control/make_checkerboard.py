#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_checkerboard.py — genera un tablero de ajedrez de calibracion a TAMAÑO FISICO EXACTO.

Para calibrar los intrinsecos de la camara (cv2.findChessboardCorners + calibrateCamera) hace
falta un patron plano de geometria conocida. OpenCV cuenta ESQUINAS INTERNAS: un tablero de
COLS x ROWS cuadros tiene (COLS-1) x (ROWS-1) esquinas internas. Se usa un conteo ASIMETRICO
(9x6) para que la orientacion no sea ambigua.

Salidas (sin dependencias externas: PDF escrito a mano + SVG de texto + PNG con cv2):
  - PDF vectorial, pagina A4 apaisada, cuadros EXACTOS en mm  -> imprimir AL 100% (tamaño real)
  - SVG de respaldo (mismas medidas)
  - PNG de vista previa (para revisar en pantalla)

CLAVE: el tamaño de cuadro real es el que MIDAS tras imprimir. Si tu impresora escala, mides
p. ej. 24.3 mm y usas ESE valor en la calibracion — el patron sigue siendo valido. Por eso el
PDF trae el nominal impreso al pie: imprime, mide un cuadro con regla, y anota el real.

Uso:  python make_checkerboard.py [--cols 10 --rows 7 --square-mm 25 --out-dir ../../data/calibration]
"""
import argparse, os

MM2PT = 72.0 / 25.4          # 1 mm en puntos PDF (72 pt = 1 pulgada)


def build_pdf(cols, rows, sq_mm, path):
    """Escribe un PDF minimo A4 apaisado con el tablero centrado y una leyenda al pie."""
    PAGE_W, PAGE_H = 297.0 * MM2PT, 210.0 * MM2PT      # A4 apaisado en puntos
    s = sq_mm * MM2PT
    board_w, board_h = cols * s, rows * s
    bx = (PAGE_W - board_w) / 2.0
    by = (PAGE_H - board_h) / 2.0 + 8 * MM2PT          # subir un poco: hueco al pie para el texto

    # --- content stream: cuadros negros (i+j par) + leyenda ---
    parts = ["1 1 1 rg 0 0 %.2f %.2f re f" % (PAGE_W, PAGE_H),   # fondo blanco explicito
             "0 0 0 rg"]
    for j in range(rows):
        for i in range(cols):
            if (i + j) % 2 == 0:
                parts.append("%.3f %.3f %.3f %.3f re" % (bx + i * s, by + j * s, s, s))
    parts.append("f")
    cap = ("Checkerboard %dx%d cuadros  |  %dx%d esquinas internas  |  cuadro = %.1f mm  |  "
           "IMPRIMIR AL 100%% \\(tamano real, sin ajustar a pagina\\) y MEDIR un cuadro con regla"
           % (cols, rows, cols - 1, rows - 1, sq_mm))
    parts.append("BT /F1 9 Tf %.2f %.2f Td (%s) Tj ET" % (bx, by - 14, cap))
    content = ("\n".join(parts)).encode("latin-1")

    # --- objetos PDF ---
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        ("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.2f %.2f] "
         "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>" % (PAGE_W, PAGE_H)).encode(),
        b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for k, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += ("%d 0 obj\n" % k).encode() + body + b"\nendobj\n"
    xref = len(out)
    out += ("xref\n0 %d\n" % (len(objs) + 1)).encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += ("%010d 00000 n \n" % off).encode()
    out += ("trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objs) + 1, xref)).encode()
    with open(path, "wb") as fh:
        fh.write(out)


def build_svg(cols, rows, sq_mm, path):
    w, h = cols * sq_mm, rows * sq_mm
    r = ['<svg xmlns="http://www.w3.org/2000/svg" width="%gmm" height="%gmm" '
         'viewBox="0 0 %g %g">' % (w, h, w, h),
         '<rect width="%g" height="%g" fill="white"/>' % (w, h)]
    for j in range(rows):
        for i in range(cols):
            if (i + j) % 2 == 0:
                r.append('<rect x="%g" y="%g" width="%g" height="%g" fill="black"/>'
                         % (i * sq_mm, j * sq_mm, sq_mm, sq_mm))
    r.append("</svg>")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(r))


def build_png(cols, rows, sq_mm, path, ppmm=6):
    import numpy as np, cv2
    s = int(round(sq_mm * ppmm))
    bw, bh = cols * s, rows * s
    m = 4 * s                                            # borde blanco (quiet zone)
    img = np.full((bh + 2 * m, bw + 2 * m), 255, np.uint8)
    for j in range(rows):
        for i in range(cols):
            if (i + j) % 2 == 0:
                y0, x0 = m + j * s, m + i * s
                img[y0:y0 + s, x0:x0 + s] = 0
    cv2.imwrite(path, img)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cols", type=int, default=10, help="cuadros a lo ancho")
    ap.add_argument("--rows", type=int, default=7, help="cuadros a lo alto")
    ap.add_argument("--square-mm", dest="sq", type=float, default=25.0, help="lado del cuadro (mm)")
    ap.add_argument("--out-dir", dest="out", default=None, help="carpeta de salida")
    a = ap.parse_args()
    here = os.path.dirname(os.path.abspath(__file__))
    out = a.out or os.path.join(here, "..", "..", "data", "calibration")
    out = os.path.abspath(out)
    os.makedirs(out, exist_ok=True)
    base = "checkerboard_%dx%d_%gmm" % (a.cols, a.rows, a.sq)
    build_pdf(a.cols, a.rows, a.sq, os.path.join(out, base + ".pdf"))
    build_svg(a.cols, a.rows, a.sq, os.path.join(out, base + ".svg"))
    build_png(a.cols, a.rows, a.sq, os.path.join(out, base + ".png"))
    print("tablero %dx%d cuadros = %dx%d esquinas internas, cuadro %.1f mm"
          % (a.cols, a.rows, a.cols - 1, a.rows - 1, a.sq))
    print("board fisico: %.0f x %.0f mm" % (a.cols * a.sq, a.rows * a.sq))
    print("salidas en: %s" % out)
    for e in (".pdf", ".svg", ".png"):
        print("  " + base + e)


if __name__ == "__main__":
    main()
