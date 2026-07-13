# Hallazgos consolidados

> Conclusiones vivas de la investigación mundial (FASE 1, 2026-07-10). Se actualizan con cada experimento. Postura invariante: **`[NO CONFIRMED PATH]`** — no hay hoy vía pública, documentada y demostrada de control del Neo; investigamos si puede descubrirse.

## Conclusión de una línea

El **enlace WiFi teléfono↔Neo es la única superficie de control reversible sin hardware DJI**, y toda la metodología (captura, dissectors DUML, unpacking de DJI Fly) ya está resuelta por terceros sobre drones DJI hermanos. Lo que falta es **trabajo dirigido específicamente al Neo**: nadie ha publicado una sola captura, tabla de cmd_id de vuelo, ni root shell del Neo, en ningún idioma. La incógnita que decide la factibilidad es si el DUML del Neo (2024) viaja **cifrado a capa de aplicación** sobre el WiFi.

## Hallazgos NUEVOS más importantes

1. **`[OBSERVED]` El código de modelo interno del Neo es `wa521`.** Visible en el binario `V01.00.0400_wa521_dji_system.bin` (issue #458 de dji-firmware-tools). Ese firmware **no** parsea con el parser `xv4` legacy ("Unexpected magic value in main header") → el Neo usa un contenedor más nuevo que las herramientas comunitarias actuales no abren. `wa521` es además la clave de búsqueda/targeting para firmware y DUML.

2. **`[CONFIRMED]` La radio principal del Neo hacia el teléfono es WiFi estándar de doble banda + BLE, NO OcuSync.** Los reportes de test FCC (FCC ID `SS3-DN1A062624`) son de WiFi 2.4G, NII-WiFi (5 GHz), BLE y SRD. El O4/OcuSync 4 solo aparece con mando/gafas. → El canal de control por teléfono es IP/WiFi, reversible en principio.

3. **`[CONFIRMED]` El mando N-series del Neo acepta comandos DUML de ESCRITURA por USB** (proyecto DJI-FCC-HACK de M4TH1EU, cambio CE→FCC, probado en Neo 2/Flip/Mini). Es prueba concreta de un canal DUML escribible que alcanza físicamente el hardware del Neo. **Matiz clave:** escribir parámetros ≠ enviar sticks de vuelo, que sigue sin documentarse para esta generación.

4. **`[CONFIRMED]` DJI mató oficialmente la ruta del SDK.** Respuesta de staff en GitHub (Mobile-SDK-Android-V5 issue #725): el MSDK no soporta Neo 1/2 y no hay planes (foco en UAV industriales). Esto mata **DJIControlServer** y **RosettaDrone** para el Neo (ambos dependen de MSDK) → el control solo puede venir de RE de protocolo crudo, no de una API.

5. **`[CONFIRMED]` El Neo se pilota con joysticks virtuales directamente por WiFi desde DJI Fly** ("Manual Control", sin mando). Implicación decisiva: la cadena completa evento-joystick → serialización → transporte → dron **existe dentro del APK** y viaja por el enlace WiFi/IP.

6. **`[EXPERIMENTAL]` SecNeo protege DJI Fly** (`libDexHelper.so`, dex cifrados con RC4, anti-Frida, XOR de strings con clave hardcodeada tipo `b'Y*IBg^Yd'` en GO 4), **PERO** Synacktiv, Quarkslab y RECON'23 **ya** desempaquetaron apps DJI hermanas volcando los ~7-8 dex con Frida/gdb + dex2jar + JADX. La metodología y las barreras están resueltas; falta el trabajo dirigido al Neo.

7. **`[OBSERVED]` El Neo escribe telemetría SRT** (GPS, altitud, ISO/shutter, frame-counter) junto al MP4 al activar subtítulos en DJI Fly, parseable con `dji-telemetry` (probado en Neo 2). Da timestamps y metadatos de cámara sincronizados por-frame (GPS inútil en interiores, pero útil para el pipeline). Los logs `.txt` (dji-log-parser, cifrado v13+) son otra fuente offline, cobertura Neo aún sin confirmar.

8. **`[INFERRED]` El firmware del Neo es contenedor IMaH v2** (AES bajo clave UFIE por plataforma + firma RSA/PRAK + TBIE). Obtenerlo es viable hoy (DankDroneDownloader lista "Neo, Neo 2"; DJI Assistant 2 lo cachea por USB-C). **Descifrarlo no tiene vía pública:** no hay evidencia de clave UFIE del Neo filtrada (para Mavic 3, misma generación, se logró con UFIE/TBIE-2022-04).

9. **`[CONFIRMED]` RTMP push nativo funciona en el Neo** desde DJI Fly (TCP 1935 hacia servidor propio, p.ej. NGINX-RTMP/MediaMTX). Resuelve el vídeo en vivo → ROS **sin ninguna RE**. Limitaciones: sale del teléfono re-encodeado (latencia + recompresión), requiere DJI Fly abierto, da solo vídeo (ni pose ni mando).

10. **`[OBSERVED, RESUELTO 2026-07-12]` El DUML del Neo por WiFi va EN CLARO — NO cifrado a capa app.** Captura propia phone-only (EXP-003, `Tercer prueba.pcap`): en el uplink tel→dron por **UDP 9003** se hallaron **6275 tramas DUML con CRC-8 de DJI VÁLIDO** (algoritmo `arr_2A103`/seed 0x77 de `comm_dat2pcap.py`). El CRC cuadra → es DUML auténtico y legible, no ruido cifrado. **Gate ABIERTO: la vía de control por WiFi es VIABLE.** Matices: el DUML viaja encapsulado en un wrapper de sesión DJI (`XX 80` + contadores), no como DUML-serie puro; cmd_set dominante `0x51/0x01` a ~34 Hz (candidato a stream de sticks), más comandos discretos (`0x01/0x0a`, `0x03/0x20` flyctrl, handshake `0x07/0x93` con UUID de sesión). Falta mapear byte↔eje con una captura controlada de un eje a la vez.

11. **`[OBSERVED, DECISIVO 2026-07-13]` El transporte es el UDP fiable de `samuelsadok/dji_protocol`, y por eso nuestros comandos eran ignorados — NO por falta de "autoridad".** El reanálisis de capturas (EXP-018) probó byte a byte que el "wrapper" es la cabecera de ese protocolo: `0x04-05` = seq (paso +8 desde el seed del hello), `0x06` = tipo, `0x07` = **XOR de bytes 0..6**, `0x08-13` = ventanas de flow-control. Nuestro emisor forjaba mal esos 3 campos (XOR = contador, seq arbitrario `0x9600` paso 32, ventanas basura) → **el dron descartaba los comandos en la capa de transporte** (su ventana RX type-5 quedaba **congelada en el seed**, vs. **avanzaba** con la app). Validación: XOR correcto en 100% de 89.000+ paquetes de la app; reconstrucción 8/8 de comandos type-5 reales. **Refuta la hipótesis de autoridad/autenticación (EXP-017).** Fix: `tools/neo_control/neo_udp.py` (builder correcto y validado). Detalle en [`EXPERIMENT_LOG.md`](EXPERIMENT_LOG.md) EXP-018.

12. **`[OBSERVED, DECISIVO 2026-07-13]` El transporte YA no es el problema; el candado del ARMADO es un canal de control de vuelo firmado/cifrado por sesión.** Con el fix de flow-control de EXP-018, el cambio de **modo** (0x03/0xf9) sí ejecuta en hardware — pero el **despegue no**. La captura de un despegue real en Manual (EXP-019, "Octava prueba", + comparación con "Quinta") resolvió por qué:
    - **El comando de despegue es `cmd_set=0x03 / cmd_id=0xda`, payload `05 ffffffff`** (subtipo 0x05 = armar/despegar). Nuestro `flight.py` ya lo construía **byte-idéntico**. No faltaba el comando.
    - **La app envuelve los comandos de control de vuelo (cmd_set 0x03) en un contenedor de "transmisión transparente" `0x51/0x01`** (emisor 0x3b→0xe9, cola de ~21 B con contador `0099d4ac02…ffffffff0182`). Los sticks (0x01/0x0a) y la telemetría van crudos. **PERO el envoltorio no es el candado:** el mismo `05ffffffff` se mandó *crudo* en Quinta y *envuelto* en Octava. Va de las dos formas.
    - **El candado real:** el armado va acompañado de (a) la variante `03` de la autoridad `0x03/0x20` con un **token de 8 B que cambia entre sesiones** (Octava `f2458601ac9a06fa` vs Quinta `0e468601049b06fa`), y (b) un stream `0x03/0xf8` con **bloques de 32/64 B que se ven cifrados** (comparten sub-bloques entre sesiones al estilo ECB, pero difieren). Nuestro emisor solo manda la variante `02` de la autoridad (token en ceros) y **nunca** `0x03/0xf8` ni el heartbeat `0x03/0xd7` (620×, `0104…`+contador) que corre durante todo el vuelo.
    - **Feasibilidad (abierta al escribir esto):** el token aparece **solo en el uplink, nunca en el downlink del dron**. Quedaba la duda de si es nonce libre (reproducible) o firma con secreto (bloqueo). **⇒ RESUELTO en EXP-020 (ver #13): es reproducible, NO hay firma.** Herramientas: `tools/neo_control/analysis/unwrap.py`. Detalle en [`EXPERIMENT_LOG.md`](EXPERIMENT_LOG.md) EXP-019.

13. **`[OBSERVED, DECISIVO 2026-07-13]` NO hay candado criptográfico en el armado: el "token" es una coordenada GPS y el "handshake cifrado" es un lote de parámetros.** Decodificando el downlink DUML del dron (EXP-020, `tools/neo_control/analysis/downlink.py`, escaneo por CRC-8 válido) se desmontaron los dos sospechosos de cifrado de #12:
    - **`0x03/0xf8` NO es reto-respuesta cifrado — es una operación por lotes de parámetros.** La app manda una lista de valores de 4 B (hashes de nombres de parámetro), y el dron responde (`snd=03 rcv=02 attr=80`) **los mismos valores con un código de estado intercalado** (`00 <val> <status> <val> <status>…`). Los "bloques aleatorios de 32/64 B" eran arrays de param-hashes, no criptografía.
    - **El "token" de `0x03/0x20` variante-03 es la COORDENADA GPS del dron (grados×10⁶), no una firma.** 4 muestras independientes (Tercer/Cuarta/Quinta/Octava): el campo A varía **solo ±224** y el campo B **solo ±140** sobre una base fija (rango ~±0.0002° ≈ ±22 m = jitter de GPS de consumo), y ambos decodifican a una **coordenada geográfica real y estable** en grados×10⁶ (**coordenada del usuario redactada por privacidad — no se versiona**). Una firma criptográfica sería uniforme en los 32 bits; esta agrupación físico-geográfica lo descarta. El dron reporta su posición en grados×10⁷ en telemetría → **la coordenada es legible/derivable en vivo**, no un secreto.
    - **Conclusión:** el armado del Neo **no exhibe un canal firmado/cifrado** en las capturas. Por qué fallaba nuestro `flight.py`: solo enviaba la autoridad variante-`02` (coordenada en ceros), nunca la variante-`03` con coordenada, ni el heartbeat `0x03/0xd7`, ni el lote de parámetros ni la ráfaga de init del despegue. **Todo eso es reproducible sin secretos.** No se necesita el APK para esta vía. Falta confirmarlo con una prueba física (reproducir la secuencia completa) — gated, supervisada. Detalle en [`EXPERIMENT_LOG.md`](EXPERIMENT_LOG.md) EXP-020.

## Mejor vía y segunda mejor

- **Mejor vía — observación pasiva del WiFi + análisis del APK (dos frentes).**
  - Para el vídeo (Hito 1): RTMP nativo (E-OBS-2) + flujo USB offline + SRT (E-OBS-1). Sin RE, ya confirmado en el Neo.
  - Para el control: capturar y decodificar el enlace WiFi teléfono↔dron (E-OBS-3/4), porque es pasivo, de bajo riesgo, la cadena joystick→WiFi→dron está confirmada, el framing DUML es maduro, y el usuario posee la PSK de su propio dron. **Punto de decisión:** si el DUML del Neo va en claro → reversar el mando es factible; si va cifrado → el frente se traslada al APK.

- **Segunda vía — análisis del APK DJI Fly (`dji.go.v5`).** Estático (E-OBS-5) → volcado dinámico con Frida de los dex descifrados por SecNeo → dex2jar + JADX (lógica Java) → Ghidra (`.so`), para extraer la tabla de comandos y el formato de serialización de los sticks del Neo **directamente del código**. Dificultad muy alta, pero la metodología ya la resolvieron Synacktiv/Quarkslab/RECON'23 sobre apps hermanas. Es **independiente de si el tráfico va cifrado**, porque recupera el productor del paquete, no el paquete en el cable. Banco de pruebas posterior: `pyduml`/`DUMLrub`/`B3YOND` para reenviar comandos una vez conocido el cmd_set/cmd_id de vuelo del Neo (`wa521`).

## Bloqueos conocidos

- `[BLOCKED]` **MSDK:** el Neo nunca estará en el Mobile SDK → DJIControlServer/RosettaDrone muertos para el Neo.
- `[BLOCKED]` **Enlace O4/OcuSync 4** (mando y gafas): carga cifrada AES-256; el RE público solo demodula el DroneID sin cifrar (NDSS'23), no el canal de mando. La inyección por O4 no tiene vía pública y sería RF potencialmente ilegal → **fuera de alcance**.
- `[BLOCKED]` **Descifrado de firmware:** contenedor IMaH v2 con clave UFIE por plataforma; no hay clave del Neo pública y el parser xv4 legacy falla en `wa521`. Obtener el `.bin` es fácil; abrirlo no.
- `[BLOCKED parcial]` **SecNeo** en DJI Fly: superable (ya hecho en apps hermanas) pero requiere dispositivo root, bypass anti-Frida y esfuerzo alto.
- `[BLOCKED]` **Root de Goggles N3 / generación O4:** WTFOS/fpv.wtf declara explícitamente que no soporta O4.
- `[UNKNOWN]` **Puerto de debug UART/JTAG del Neo:** SoC y MCU bajo blindaje con pasta térmica en fotos FCC; ningún teardown mapeó test pads. Vía invasiva y de alto riesgo, a aplazar.
- **Ausencia total de trabajo previo público específico del Neo:** no hay pcap, ni tabla cmd_id de vuelo, ni root shell publicados en ningún idioma. Hay que generar la evidencia primaria uno mismo.

## Primer experimento físico recomendado

**E-OBS-1**: conectar el **dron** (no el mando) por USB-C al PC y, sin flashear nada: (1) enumerar las interfaces USB para ver si expone solo almacenamiento masivo o también un puerto serie/CDC-ACM (candidato DUML); (2) leer la versión exacta de firmware con DJI Assistant 2 en modo solo-lectura y confirmar el código interno `wa521`; (3) extraer y parsear el SRT de una grabación corta (subtítulos activados) para validar la telemetría por-frame. Riesgo esencialmente nulo, y fija la línea base de todo lo demás.

## Preguntas abiertas críticas

- ~~¿El DUML del Neo viaja cifrado a capa app sobre el WiFi?~~ **RESUELTO 2026-07-12 (EXP-003): NO, va en claro.**
- ~~¿Se puede hacer replay/craft de un comando aceptado por el dron?~~ **RESUELTO 2026-07-13 (EXP-018): el fallo era el wrapper de transporte mal forjado (XOR/seq/ventanas), no el DUML. Builder corregido y validado 8/8 contra la app.** Nueva pregunta que lo reemplaza: con el wrapper type-5 correcto, ¿ejecuta el dron el comando (empezando por `set-modo` inocuo) — la ventana RX avanza y/o el modo cambia en telemetría?
- ¿Expone el Neo un CDC-ACM DUML por USB-C, o solo almacenamiento masivo? (E-OBS-1).
- ¿Aparecerá la clave UFIE del Neo (como pasó con Mavic 3) para desbloquear el firmware?
- ¿Alguien publicará el primer pcap del Neo en alguna comunidad? (monitorizar `wa521`).
