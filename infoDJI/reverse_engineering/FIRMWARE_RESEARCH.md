# Investigación de firmware del Neo

> Resumen: **obtener** el firmware del Neo es viable hoy; **descifrarlo/analizarlo** no tiene vía pública demostrada aún. La barrera no es el archivo, es la clave.

## Versiones y obtención

- **`[CONFIRMED]`** El firmware del Neo existe con versiones públicas: **V01.00.0300** (2024-09-29) y **V01.00.0400** (2024-11-06). DJI **no** publica el `.bin` directo en su web (solo PDFs de release notes); se distribuye por OTA en DJI Fly o por DJI Assistant 2.
- **`[EXPERIMENTAL]`** **DankDroneDownloader (DDD)** lista explícitamente **"Neo, Neo 2"** y descarga desde los servidores de DJI (flujo autenticado; errores 401 ligados a la hora del sistema). Vía pública más práctica para obtener el paquete.
- **`[OBSERVED]`** **DJI Assistant 2** (rama Consumer, v2.1.28) soporta el Neo por USB-C: conectar el dron, ver/descargar actualizaciones (cachea el paquete en disco). Vía oficial-alternativa.
- **`[CONFIRMED]` (Mavic 3, `[INFERRED]` Neo)** El endpoint autenticado de descarga es una REST a `mydjiflight.dji.com/getfile/downpath`, interceptable entre DJI Fly y la nube (método Nozomi).

## Formato y cifrado (la barrera real)

- **`[INFERRED]`** El contenedor es casi con certeza **IMaH v2** (formato `IM*H`, usado por todos los DJI desde 2018; drones de 2024 caen en v2, que reutiliza un único cifrador por módulo).
- **`[CONFIRMED]`** El payload va **cifrado con AES bajo una clave UFIE específica de plataforma**, firmado con **RSA (claves PRAK)**, con **TBIE** para arranque seguro. `dji_imah_fwsig.py` conoce las familias de claves (UFIE-*, TBIE-*, RREK/RIEK/PUEK, PRAK/RRAK/SLAK); el descifrado real requiere la UFIE correcta.
- **`[BLOCKED]`** No hay evidencia pública de que la clave UFIE del Neo esté disponible. Para Mavic 3 (misma generación) se logró con **UFIE/TBIE-2022-04** (divulgadas por Felix Domke + repo dji-firmware-tools). Para el Neo (2024) el wrapping key podría ser una UFIE/PUEK más reciente no publicada.
- **`[OBSERVED]`** El parser legacy `xv4` **falla** en el firmware del Neo: `dji_xv4_fwcon.py` sobre `V01.00.0400_wa521_dji_system.bin` → *"Unexpected magic value in main header"* (issue #458). Confirma contenedor más nuevo **y** revela el código de modelo **`wa521`**.

## Qué se podría hacer con el firmware (si se descifrara)

- **`[INFERRED]`** OS basado en **Android sobre ARM**, con lado trusted en **ARM TrustZone** (extrapolado del análisis de Mavic 3: particiones system/vendor, binarios de servicios del dron).
- Flujo de análisis post-descifrado (probado en Mavic 3): `dji_imah_fwsig.py` → desempaquetar `system.new.dat.br`/`vendor.new.dat.br` con **brotli + sdat2img** a ext4 montable, rootfs con **cpio**, reconocimiento con **binwalk** (inútil sobre `IM*H` aún cifrado, solo ve alta entropía). Objetivo: hallar cmd_set/cmd_id de control, product IDs, tablas DUML, cómo el Neo construye/cifra sus paquetes.

## Estado de root / exploits

- **`[UNKNOWN]`** No hay root, shell ni custom firmware demostrado en el Neo. Los exploits DUML (DUMLRacer ≤`v01.04.0200`, DUMLdore, margerine) son de **generaciones anteriores**. No es imposibilidad: es ausencia de vía pública.
- **`[UNKNOWN, low]`** Existe un "DJI Decrypt Tool" oficial, pero no consta que descifre el firmware de aeronave del Neo (alcance sin aclarar).

## Prioridad para el proyecto

Ruta de **largo plazo**, no de control a corto. Acción concreta de bajo coste: descargar el paquete con DDD, archivar `.sig`/`.bin`, ejecutar `dji_imah_fwsig.py` con las claves públicas conocidas para **confirmar/negar** que alguna sirve (esperado: falla → documentar que la UFIE del Neo falta). Si algún día aparece la clave (como pasó con Mavic 3), esta ruta se reactiva.

**Fuentes clave:** `cs2000/DankDroneDownloader`; `o-gs/dji-firmware-tools` (`dji_imah_fwsig.py`, issue #458, wiki); Nozomi "DJI Mavic 3 research part 1"; `dji.com/downloads/products/neo`; DJI Assistant 2 (Consumer); `CunningLogic/DUMLRacer`; Neodyme "drone hacking part 1". Lista completa en [`SOURCES.md`](SOURCES.md).
