# Superficie de investigación y matriz de rutas

> Estado: 2026-07-10, tras la investigación mundial (FASE 1). Todas las rutas se ordenan por relación *probabilidad de dar control / riesgo*. **Ninguna ruta tiene hoy una demostración pública sobre el Neo**; lo que sigue es la superficie real por donde atacar el problema, con evidencia y siguiente experimento.

## Mapa de la cadena que queremos intervenir

```
[Dedo en joystick virtual de DJI Fly]
        │  (dentro del APK dji.go.v5, protegido por SecNeo)
        ▼
[Representación interna de control]  ──►  serialización (¿DUML? ¿protobuf?)
        ▼
[Transporte]  ── WiFi P2P (WPA2-PSK/CCMP, UDP)  ──►  [DJI Neo]  ──► reacción física
        │
        └── (alternativa con mando/gafas: enlace O4/OcuSync 4 cifrado AES-256 — superficie distinta, mucho más dura)
```

Hay **tres puntos de intervención** posibles:
1. **El cable / el aire** — capturar el transporte (WiFi UDP) y decodificarlo → rutas de red.
2. **El productor del paquete** — el APK DJI Fly, donde nace el comando → rutas de software.
3. **El propio dron** — por USB-C (DUML) o por firmware/hardware → rutas de dispositivo.

## Matriz de rutas

| Ruta | Evidencia (hoy) | Dificultad | Prob. de dar control | Riesgo | Próximo experimento |
|---|---|---|---|---|---|
| **WiFi/red — análisis de paquetes** | `[CONFIRMED]` arquitectura DJI WiFi (AP WPA2-PSK/CCMP, DHCP, UDP) verificada en Mavic Pro 1 (tesis JKU). El usuario posee la PSK de su dron → puede descifrar. `[UNKNOWN]` si el DUML del Neo va cifrado a capa app. | Media | **Media** | **Muy bajo** (pasivo) | E-OBS-3 / E-OBS-4 |
| **Captura de tráfico en Android** | `[EXPERIMENTAL]` PCAPdroid captura DJI Fly↔Neo sin root (el móvil es un extremo). No descifra capa-app si existiera. | Baja | Media | Muy bajo | E-OBS-3 |
| **DJI Fly — análisis estático** | `[CONFIRMED]` APK `dji.go.v5` protegido por SecNeo (libDexHelper.so, dex RC4, XOR strings). Estático "a secas" no revela el control. | Alta | Media | Bajo (solo software) | E-OBS-5 |
| **DJI Fly — análisis dinámico (Frida)** | `[EXPERIMENTAL]` Synacktiv/Quarkslab/RECON'23 ya volcaron 7-8 dex con Frida en apps DJI hermanas. Falta el trabajo dirigido al Neo. | Muy alta | **Media-alta** (si se aísla la serialización del stick) | Bajo-medio (baneo de cuenta DJI Fly) | tras E-OBS-5 |
| **Investigación DUML** | `[CONFIRMED]` framing maduro y agnóstico de producto (0x55, cmd_set/cmd_id, CRC-8/CRC-16, ~17 command sets, 0x03 = flight controller). `[UNKNOWN]` cmd_id de vuelo del Neo + auth de sesión. | Media | Media | Bajo si solo lectura; **alto si se envían cmd de vuelo** | E-OBS-1 (lectura) → probing |
| **Extracción de firmware** | `[INFERRED]` obtenible (DankDroneDownloader lista "Neo, Neo 2"; Assistant 2 lo cachea). `[BLOCKED]` descifrado: contenedor IMaH v2, sin clave UFIE del Neo pública; parser xv4 legacy falla en firmware `wa521`. | Alta (obtener: baja / descifrar: muy alta) | Baja (corto plazo) | Bajo (offline) | archivar `.bin` + intentar claves conocidas |
| **DJI Assistant 2** | `[CONFIRMED]` soporta Neo por USB-C (update/rollback, calibración, export de logs). Debug Mode oculto parcheado en builds recientes. | Baja | Baja (no da API de mando) | Bajo-medio (evitar flashing) | E-OBS-1 |
| **RC / Goggles (O4)** | `[CONFIRMED]` mandos/gafas usan O4 cifrado AES-256, no WiFi. `[CONFIRMED]` el mando N-series acepta DUML de **escritura** por USB (DJI-FCC-HACK). `[BLOCKED]` O4 en vuelo (solo DroneID sin cifrar es demodulable, NDSS'23); `[BLOCKED]` root de Goggles N3 (WTFOS no cubre O4). | Muy alta (RF O4) / Media (DUML por USB al mando) | Baja (control de vuelo por O4) | Bajo por USB; **muy alto/ilegal por RF** (fuera de alcance) | opcional: reproducir DJI-FCC-HACK |
| **Interfaces de debug HW (UART/JTAG)** | `[UNKNOWN]` SoC y MCU bajo blindaje con pasta térmica en fotos FCC; ningún teardown mapeó test pads. Contraejemplo: Neodyme no halló UART/JTAG en Potensic Atom 2. | Muy alta | Baja-media (largo plazo) | **Alto** (invasivo: abrir el dron) | APLAZAR hasta agotar software |
| **Proyectos open-source existentes** | `[CONFIRMED]` DJIControlServer/RosettaDrone dependen de MSDK → muertos para Neo. Base reutilizable: dji-firmware-tools, pyduml, DUMLrub, D3VL/B3YOND. Ninguno lista `wa521`. | Baja (reuso de tooling) | Media (como andamiaje) | Muy bajo | clonar + validar dissectors contra captura propia |
| **Comunidad (multilingüe)** | `[OBSERVED]` techo en TODOS los idiomas (EN/ZH/RU/DE/FR) = parameter/region mods (FCC/NFZ/M-mode), nunca mando ni telemetría externa. | Baja | Baja (para hallar control ya hecho) | Muy bajo | monitorizar hilos Neo por `wa521` / primer pcap |

## Lectura de la matriz

- **Máxima prioridad (bajo riesgo, información alta):** observación pasiva del WiFi + análisis del APK. Son las dos rutas que atacan la *única superficie de control reversible sin hardware DJI* (el enlace WiFi teléfono↔dron) desde sus dos extremos: el cable y el productor.
- **El gate que decide todo:** si el DUML del Neo (2024) viaja **en claro** sobre el WiFi (como en Mavic Pro 1, 2016) → reversar el mando por captura es factible. Si va **cifrado a capa app** → la ruta se traslada al análisis del APK (que recupera el productor, no el paquete). Resolver este gate es el objetivo de E-OBS-3/E-OBS-4.
- **Bloqueos duros conocidos:** MSDK (muerto para Neo), O4 en vuelo (cifrado, además RF potencialmente ilegal → fuera de alcance), descifrado de firmware (falta clave UFIE), root de Goggles N3 (WTFOS no cubre O4).
- **Aplazar:** hardware invasivo (abrir el dron) solo tras agotar software.

Ver el plan concreto en [`EXPERIMENT_PLAN.md`](EXPERIMENT_PLAN.md) y los detalles por dominio en `NETWORK_RESEARCH.md`, `DJI_FLY_RESEARCH.md`, `DUML_RESEARCH.md`, `FIRMWARE_RESEARCH.md`, `HARDWARE_INTERFACES.md`.
