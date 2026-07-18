# Brief de investigación: preview de vídeo EN VIVO de un stream HEVC "sucio" (DJI Neo)

Documento para pasar a un asistente de investigación (ChatGPT). Es autocontenido: no
necesita conocer el resto del proyecto. Objetivo: encontrar una forma de mostrar el vídeo
casi en vivo (para supervisar) que no sea ni "fea" (artefactos) ni "lenta".

## 1. Contexto mínimo

- Controlo un dron **DJI Neo** por software propio (ingeniería inversa del protocolo Wi‑Fi/UDP;
  no uso la app DJI Fly ni SDK oficial). Recibo el vídeo de la cámara como paquetes UDP.
- El códec es **HEVC / H.265, 1080p (1920×1080), ~30 fps**, en **Annex‑B** (NAL units con
  start codes `00 00 00 01`).
- Reensamblo los frames a partir de los paquetes UDP: cada frame de vídeo llega en varios
  paquetes MTU (con duplicados y a veces desorden). Mi reensamblador **deduplica y ordena**,
  y **descarta frames incompletos**. Salida típica de una corrida: ~1157 frames completos,
  ~10 descartados. El *elementary stream* resultante empieza con `00 00 00 01 40` (NAL VPS,
  tipo 32), o sea el keyframe/parameter sets al inicio.
- **Hay UN SOLO keyframe (IDR) al inicio** del clip. El encoder del Neo emite IDR naturales
  muy espaciados (~cada 33 s), así que en clips cortos hay 1 solo. No controlo el encoder
  (no puedo pedirle IDRs más frecuentes por ahora).
- El stream en vivo tiene **pérdidas de paquetes**, así que al decodificar aparecen errores:
  - `PPS id out of range: 0`
  - `Could not find ref with POC <n>`
  - `missing picture in access unit with size 7`
  Esto genera artefactos ("se ve neblinoso") pero el vídeo es reconocible.

## 2. Entorno (exacto)

- **Windows 11**, PowerShell.
- **Python 3.14.5** en un venv.
- **OpenCV `cv2` 5.0.0** (build con GUI: `Win32 UI: YES`, `highgui` presente; `imshow`
  funciona). Trae ffmpeg embebido.
- **PyAV 18.0.0** (`av`), wheel `cp311-abi3`, también con ffmpeg embebido.
- **NO hay binario ffmpeg/ffplay instalado en el sistema** (ni en PATH). WSL2 está instalado
  pero **sin ninguna distro Linux**.
- Un solo proceso Python maneja TODO: red (control del dron + recepción de vídeo), y quiero
  que el preview viva en ese mismo proceso (el dron solo admite **un cliente**; no puedo
  abrir una segunda conexión desde otro proceso).
- Hay un **lazo de control en tiempo real** (envía sticks a 20 Hz, ACKs a 30 Hz). El preview
  **no debe perturbarlo** (idealmente decodificar en un hilo aparte; pintar la ventana en el
  hilo principal, porque en Windows la GUI de OpenCV solo es fiable desde el hilo principal).

## 3. Objetivo

Mostrar el vídeo **casi en vivo** durante un vuelo de ~40 s para **supervisar la cobertura**
(ver hacia dónde apunta la cámara, si cubre las zonas). NO hace falta FPV suave ni baja
latencia perfecta: un refresco de ~2‑4 fps con ~1‑2 s de retraso sería aceptable. Lo que NO
es aceptable es lo que obtengo hoy (ver abajo): lento creciente y feo.

## 4. Lo que probé y los resultados (MEDIDOS)

Todo sobre el mismo clip real reensamblado (`.h265` Annex‑B, ~2–16 MB según duración).

1. **cv2.VideoCapture(archivo)** → **SÍ decodifica** (tolerante: muestra frames corruptos).
   - 2.12 MB / 447 frames → **1.13 s** de decode.
   - 16.8 MB / 1157 frames → **varios segundos**.
   - Problema: solo decode **completo desde el inicio**. Como el archivo **crece** durante el
     vuelo, cada refresco redecodifica TODO → cada vez más lento ("muy lento").
   - Probado: `VideoCapture` sobre un **archivo que crece** (abrir, leer hasta EOF, **append**
     de más bytes, seguir leyendo con el MISMO cap) → **0 frames nuevos** tras EOF. No hace
     "tail ‑f". Reabrir = volver a decodificar desde el keyframe = mismo coste.

2. **PyAV `CodecContext.create('hevc','r')` + `parse()`/`decode()`** (decodificador crudo,
   alimentado incrementalmente por bytes):
   - Inconsistente/fallo: **0 frames** en el clip de 2 MB; 394 de 1659 en otro de 9 MB.
   - Alimentando payloads crudos (sin reensamblar) → 0 frames (obvio: fragmentos MTU
     duplicados/desordenados).

3. **PyAV `av.open(archivo, format='hevc')` + demux/decode** (usa el demuxer, como cv2):
   - **0 frames.** ffmpeg detecta bien el stream (`format: hevc`, `streams: [('video','hevc')]`)
     pero no emite ningún frame.
   - Con opciones `{'flags2':'+showall'}`, `{'err_detect':'ignore_err'}`, y ambas → **sigue 0**.
   - Hipótesis: PyAV/ffmpeg por defecto **descarta frames corruptos**; cv2 los muestra igual.
     No logré que PyAV emitiera los frames corruptos.

**Resumen del bloqueo:** el único decodificador que traga nuestro stream "sucio" es
`cv2.VideoCapture`, pero solo hace decode **completo** (no incremental, no sigue archivo que
crece). PyAV haría decode **incremental barato** (cada frame una vez), pero **no emite** los
frames por los errores del stream.

## 5. Preguntas de investigación (lo que necesito)

1. **PyAV: emitir frames corruptos.** ¿Cómo configurar PyAV 18 (ffmpeg embebido) para que
   emita frames aunque haya `Could not find ref` / `PPS out of range`, igual que hace
   `cv2.VideoCapture`? Busco el equivalente exacto a `AV_CODEC_FLAG_OUTPUT_CORRUPT` y/o
   `AV_CODEC_FLAG2_SHOWALL` y/o error concealment (`ec`), aplicados sobre
   `stream.codec_context` ANTES de decodificar (¿`codec_context.flags |= ...`?
   ¿`codec_context.flags2`? ¿`options=` en `av.open`? ¿nombres correctos en PyAV?).
   Código concreto que funcione, por favor.

2. **Decode incremental de un stream que crece, en el MISMO proceso.**
   - (a) **PyAV con file‑like/callback**: ¿cómo pasar a `av.open()` un objeto **no‑seekable**
     cuyo `read(n)` **bloquea** esperando más bytes (nunca devuelve EOF hasta que yo lo
     mande)? ¿Funciona el demuxer así para un stream infinito? Gotchas en Windows.
   - (b) Alternativa: `av.CodecContext` alimentado con `parse()`/`decode()` que SÍ emita
     frames (combinado con la pregunta 1). ¿Es esta la vía más robusta para Annex‑B con
     parameter sets in‑band y pérdidas?

3. **cv2.VideoCapture sobre un stream vivo.** ¿Se puede alimentar `cv2.VideoCapture` con un
   **named pipe** en Windows (`\\.\pipe\...`) o `pipe:` vía backend FFMPEG, escribiéndole yo
   los bytes del stream a medida que llegan? ¿Sintaxis y limitaciones reales en Windows +
   OpenCV 5.0 (sin ffmpeg de sistema, solo el embebido)? ¿Devuelve frames de forma continua
   sin reabrir?

4. **Parameter sets / extradata.** Dado que el stream trae VPS/SPS/PPS in‑band solo al
   inicio (1 keyframe), ¿ayudaría **inyectar/repetir** los parameter sets periódicamente en
   el elementary stream que le doy al decoder, o pasar la **extradata** explícita al
   `CodecContext`? ¿Cómo se hace en PyAV? ¿Reduciría los `PPS out of range`?

5. **Latencia/robustez del enfoque correcto.** Para un stream HEVC en vivo con pérdidas y
   keyframes escasos, ¿cuál es el patrón estándar (biblioteca + configuración) para un
   **preview tolerante a errores, incremental (cada frame una vez), en Python en Windows**,
   sin depender de un binario ffmpeg de sistema (solo `cv2 5.0` y/o `PyAV 18`, ambos con
   ffmpeg embebido)?

6. **Plan B — transcodificar a MJPEG/HTTP.** Si lo anterior no es viable, ¿cuál es la forma
   más simple de exponer el vídeo como **MJPEG sobre HTTP** (para verlo en el navegador) desde
   Python en Windows, decodificando con lo que ya tengo (cv2/PyAV) y re‑emitiendo JPEGs? ¿Vale
   la pena vs. instalar ffmpeg de sistema y hacer `... | ffplay`?

## 6. Restricciones y no‑objetivos

- **No** puedo abrir una segunda conexión al dron (un solo cliente). El decode debe consumir
  los bytes que ya recibe el proceso de control.
- **No** quiero perturbar el lazo de control (20 Hz sticks / 30 Hz ACK). Decode en hilo
  aparte; GUI en hilo principal.
- Prefiero **no instalar** un ffmpeg de sistema si hay solución con `cv2`/`PyAV` embebidos,
  pero está sobre la mesa si es lo único robusto (evaluar coste/beneficio).
- El vídeo **grabado** (post‑vuelo) ya funciona bien con `cv2.VideoCapture`; esto es SOLO para
  el preview EN VIVO.

## 7. Datos crudos útiles

- Primer NAL del stream: `00 00 00 01 40 01 0c 01 ...` (VPS). Le siguen SPS (`...42`), PPS
  (`...44`) y luego slices.
- Errores repetidos del decoder (ffmpeg): `PPS id out of range: 0`,
  `Could not find ref with POC <n>`, `missing picture in access unit with size 7`.
- Tamaño/duración: ~0.4–0.5 MB/s de elementary stream (un vuelo de 40 s ≈ 16 MB, ~1160 frames).
- Reensamblado ya resuelto (dedup de fragmentos MTU + orden por frame + descarte de
  incompletos). El problema es SOLO decodificar+mostrar en vivo lo ya reensamblado.
