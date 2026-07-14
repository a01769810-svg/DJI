# Bitácora de experimentos

> Registro cronológico de experimentos ejecutados sobre el DJI Neo. Un bloque por ejecución. El **plan** de experimentos (los que aún no se han hecho) vive en `EXPERIMENT_PLAN.md`; aquí solo se anota lo ya ejecutado y su resultado real.

Plantilla para cada entrada:

```
## [FECHA] EXP-NNN — <título>
- Estado: [OBSERVED] / [FAILED] / [BLOCKED] / [EXPERIMENTAL]
- Objetivo:
- Setup (dron/teléfono/PC/herramientas/versión firmware):
- Pasos ejecutados:
- Resultado observado (datos crudos, rutas a capturas/pcap/logs):
- Interpretación (separar [OBSERVED] de [INFERRED]):
- Qué aprendimos (incluso si falló):
- Siguiente paso:
```

## Setup del laboratorio (confirmado por el usuario, 2026-07-10; actualizado 2026-07-12)

- **Dron:** DJI Neo original (2024). **Firmware de la aeronave = `01.00.0400`** (confirmado 2026-07-12 por pantalla Info de DJI Fly; resuelve E-OBS-1). App DJI Fly 1.21.4. WiFi `DJI-NEO-XXXX`. SN aeronave/FC = `<serial-neo-redactado>` (coincide con el decodificado de telemetría), SN cámara `7YZFN3K3130NQX`, SN batería `87HKN481G12GB5`.
- **Control disponible:** teléfono (WiFi) + mando **RC-N3**. Sin gafas (O4 fuera de alcance de todos modos).
- **Teléfono:** Android + iOS disponibles → se usa **Android** para toda captura/análisis.
- **Android de laboratorio (2026-07-12):** el usuario dispone ahora de un Android **mejor**, pero **SIN root** (confirmado por Root Checker / verificación: "no root access"). Implicación: PCAPdroid arranca en **modo VPN local (sin root)**, no en root capture; Frida (E-OBS-5, análisis dinámico) queda condicionado a rootear este u otro dispositivo más adelante.
- **Adaptador WiFi monitor 5 GHz:** no confirmado → E-OBS-4 (captura externa) queda en espera; E-OBS-3 (PCAPdroid) no lo necesita.
- **Punto de arranque elegido:** E-OBS-3 (captura WiFi) en **modo VPN sin root**. Guía en [`E-OBS-3_GUIA.md`](E-OBS-3_GUIA.md).
- **PC listo (Parte 0, verificado 2026-07-12):** Wireshark 4.6.6 en `C:\Program Files\Wireshark\`; repo `o-gs/dji-firmware-tools` clonado en `tools\dji-firmware-tools\`; dissector DUML cargando **sin errores de Lua**, protocolo `DJI_DUMLv1` + tablas `flyc/camera/gimbal/general` registradas. Instalado como un único `init.lua` en `%APPDATA%\Wireshark\plugins\` que hace `dofile` al repo (NO copiar los scripts sueltos al plugins: rompe el orden de carga). En un `.pcap`, usar *Decode As → dji_dumlv1* sobre el puerto UDP del mando.

---

## 2026-07-12 EXP-001 — Primera captura WiFi con PCAPdroid (volada con RC, no phone-only)
- Estado: [OBSERVED] — parcial; no resuelve el gate por ruta equivocada, pero deja pistas fuertes.
- Objetivo: E-OBS-3 captura 3A/3B; aislar canal de mando WiFi y ver si DUML va en claro.
- Setup: DJI Neo original; Android **sin root**; PCAPdroid **modo VPN**, target DJI Fly; PC Wireshark 4.6.6. **Se voló con el mando RC-N3** porque en conexión solo-teléfono el móvil se desconectaba del dron al activar la VPN (Android abandona la WiFi sin internet). Captura: `PCAPdroid_12_jul_17_07_53.pcap` (4.07 MB, 2865 frames).
- Resultado observado:
  - ~4 MB = TLS a servidores DJI/nube (43.109.9.11 con 3.3 MB, rangos AWS/Tencent) → cifrado, irrelevante para control.
  - Enlace con el dron `192.168.2.1`: **solo UDP :9003, teléfono→dron, 122 paquetes IDÉNTICOS de 48 B**. Sin vídeo ni telemetría por WiFi (se fueron por el RC/O4).
  - Payload 9003 (constante): `308008df0000006738f864006400c005140000640000019001c005140000640014006400c00514000064000101040102`
- Interpretación:
  - [OBSERVED] El puerto **UDP 9003** es el canal teléfono→dron por WiFi (heartbeat/mando).
  - [OBSERVED] El payload **NO empieza por `0x55`** (no es DUMLv1 clásico); empieza por `0x30`. Protocolo DJI distinto → el dissector `dji-dumlv1` no lo decodifica directo.
  - [INFERRED] Payload en **binario plano/estructurado, baja entropía** (campos repetidos `0x64`=100 → probables canales de stick en neutro). Señal de que el mando WiFi **no va cifrado a capa app** → gate probablemente ABIERTO, pendiente de confirmar con movimiento.
  - [OBSERVED] Constante 122× porque el **RC** tenía autoridad de control; el teléfono solo emitía heartbeat neutro.
- Qué aprendimos aunque no cerró el gate: (1) hay que volar **phone-only** para que los sticks viajen por WiFi; (2) target de análisis = **UDP 9003**; (3) el framing NO es DUML `0x55`, hay que reversar la estructura propia del Neo.
- Siguiente paso: repetir captura **sin RC**, resolviendo la desconexión (modo avión + solo WiFi, "mantener WiFi sin internet"), con secuencia de sticks 3B anotando tiempos. Comparar bytes de :9003 en movimiento vs el neutro de arriba.
- Archivo renombrado a `Primera prueba.pcap`.

## 2026-07-12 EXP-002 — Intento phone-only con RC encendido: dron RECHAZA el control
- Estado: [OBSERVED] — falla esperada, pero muy informativa; descarta la VPN como problema.
- Objetivo: conectar phone-only y capturar; DJI Fly mostró warning "no puedes conectar dos dispositivos a la vez / interferencia de red".
- Setup: igual que EXP-001 pero intentando conexión por teléfono **con el RC-N3 aún activo**. Captura: `Segunda prueba.pcap` (1080 B, 17 frames).
- Resultado observado:
  - 16 intentos TCP `teléfono(10.215.173.1) → dron(192.168.2.1):6001` [SYN], cada uno respondido por el dron con **[RST, ACK]** (conexión rechazada).
- Interpretación:
  - [OBSERVED] El control WiFi del Neo abre una conexión **TCP al puerto 6001** del dron (canal de comando), además del **UDP 9003** (sticks/heartbeat visto en EXP-001).
  - [OBSERVED] El dron **rechaza activamente** (RST) el control por teléfono mientras el **RC tiene autoridad** → es el "dos dispositivos a la vez" en crudo. El dron es alcanzable (responde), solo dice "no" al control.
  - [OBSERVED, importante] El SYN llega al dron y el RST vuelve → **PCAPdroid (VPN, sin root) reenvía bien el tráfico**. La VPN **NO** es el problema; queda descartada como causa de las desconexiones.
- Qué aprendimos: (1) hay que **apagar el RC** para que el dron acepte al teléfono; (2) canales de control WiFi = **TCP 6001 + UDP 9003** (filtrar ambos en la captura buena); (3) el enlace de captura funciona, así que una vez el dron acepte al teléfono la captura será válida.
- Siguiente paso: **apagar RC por completo**, conectar phone-only (modo WiFi/Connect via Mobile Device), confirmar enlace estable en tierra, y recién capturar la secuencia de sticks.

## 2026-07-12 EXP-003 — Captura phone-only con vuelo real: GATE RESUELTO, DUML EN CLARO ✅
- Estado: [OBSERVED] — ÉXITO. Resuelve la pregunta crítica de todo el proyecto.
- Objetivo: E-OBS-3 con vuelo real phone-only; ver si el control del Neo por WiFi va cifrado o en claro.
- Setup: DJI Neo original; Android **sin root**; PCAPdroid **modo VPN**; **conexión manual a la red WiFi del Neo con la contraseña** (esto destrabó todo — antes se desconectaba). RC **apagado**. Vuelo: despegue, arriba, abajo (con esperas), giro un lado, giro otro, adelante, atrás, aterrizaje (tiempos NO anotados con precisión). Captura: `Tercer prueba.pcap` (45.16 MB, ~118 s).
- Resultado observado:
  - Todo el tráfico con el dron `192.168.2.1`, 46 MB. Canal **UDP 9003** bidireccional: dron→tel (vídeo, ~37k pkts) y **tel→dron (control, ~11k pkts)**. **TCP 6001** conectó (99 pkts, ya sin RST).
  - Uplink 9003: paquete dominante de 42 B @ ~48 Hz (wrapper `22 80` + 2 contadores de 16b que rampan/desbordan + 1 campo tipo-stick duplicado en offset 16-19); paquetes más grandes (69/84/103/131 B) con wrapper `3d/4c/7b 80` que **embeben tramas DUML**.
  - **Escaneo DUML con el CRC-8 real de DJI (tabla `arr_2A103`, seed 0x77, de `comm_dat2pcap.py`): 6681 tramas `0x55`, de ellas 6275 con CRC-8 VÁLIDO.** → DUML auténtico, NO coincidencia, NO cifrado a capa app.
  - cmd_set/cmd_id vistos (uplink): **0x51/0x01 ×4045** (frames 103 B, ~34 Hz → candidato a control/joystick en tiempo real), **0x01/0x0a ×1491** (special, 31 B), 0x00/0x01 ×498 (general), 0x03/0x20 ×24 (flyctrl), 0x18/0x37, 0x18/0x3c, 0x07/0x93 (contiene UUID de sesión ASCII `2020ee4d-6aca-466f-...`), etc.
- Interpretación:
  - [OBSERVED, decisivo] **El control del Neo por WiFi es DUML EN CLARO.** El CRC-8 de DJI valida 6275 frames → gate ABIERTO. La vía de control programático por sniffing/replay WiFi es **VIABLE**.
  - [OBSERVED] Transporte: DUML encapsulado en un wrapper de sesión DJI (bytes `XX 80` + contadores) sobre UDP 9003. NO es DUML-sobre-serie puro; el dissector `dji-dumlv1` no lo auto-detecta por el offset del wrapper.
  - [INFERRED] `0x51/0x01` (~34 Hz) es el stream de mando en tiempo real (sticks); los demás son comandos discretos (arm/modo/handshake). Falta mapear qué bytes = qué eje.
  - [OBSERVED] La clave para conectar phone-only fue **unirse manualmente a la WiFi del Neo con contraseña** (no desde el flujo de DJI Fly), lo que evitó el conflicto de sesión.
- Qué aprendimos: **la pregunta crítica del proyecto (¿DUML cifrado?) queda respondida: NO.** Ver FINDINGS.md #10.
- Siguiente paso: captura **controlada de un solo eje a la vez con tiempos anotados** (secuencia 3B con cronómetro) para correlacionar el payload de `0x51/0x01` (y `0x01/0x0a`) con cada eje → mapa throttle/yaw/pitch/roll. Luego: intentar replay/craft de un comando con el dron asegurado y sin hélices.
- Archivos de análisis: `scratchpad/duml2.py` (escáner DUML+CRC), `findaxes.py`, `timeseries.py`.

## 2026-07-12 EXP-004 — Captura controlada (secuencia etiquetada): canal de sticks IDENTIFICADO
- Estado: [OBSERVED] — éxito parcial. Canal de mando localizado; mapeo fino de ejes pendiente.
- Objetivo: con secuencia conocida (arranca, IZQ, DER, ATRÁS, ADEL, ARRIBA, ABAJO, GIRO-IZQ, GIRO-DER, aterriza; 5 s neutro entre cada una) mapear qué bytes = qué eje.
- Setup: igual EXP-003, phone-only. Captura: `Cuarta prueba.pcap` (77.7 MB, ~150 s uplink).
- Resultado observado:
  - **Canal de sticks = DUML `cmd_set 0x01 / cmd_id 0x0a`, trama de 41 bytes, ~20 Hz, CONTINUA** desde justo tras el despegue hasta el aterrizaje (2567 tramas). Es el único stream continuo durante todo el vuelo manual.
  - Trama neutra de referencia (sticks centrados): `552904c902a9efa000010a01 0d0000042000010840000200000655010456087ff8 000000000000 4b5e` (header 11B, payload 28B, CRC16). Neutros por byte de payload (frame idx): [16]=32 [18]=1 [19]=8 [20]=64 [29]=86 [30]=8 [31]=128 [32]=123.
  - **Comandos de armado/despegue** agrupados solo al inicio (buckets 0-5): `0x00/0x01` (274), `0x03/0x20` flyc (22), `0x11/0x4a` (43), `0x18/0x47`, `0x00/0x99`, `0x00/0x51`. Candidatos a takeoff/arm/modo.
  - El paquete de 34 B (`22 80`) es un **heartbeat constante** (no lleva sticks). Contenedor `0x51/0x01` = telemetría multiplexada (tamaños variables), no sticks limpios.
- Interpretación:
  - [OBSERVED] El mando de vuelo en tiempo real viaja en `0x01/0x0a`. Bytes activos del payload: idx frame 18-21 y 29-32 (candidatos a ejes), pero las deflexiones fueron **pequeñas/ruidosas** → no se pudo asignar cada eje a un byte con confianza en esta toma. Los picos más claros (b18/b19) caen en la región temporal de ARRIBA/ABAJO (throttle).
  - [INFERRED] Entradas de stick suaves + fuerte estabilización del Neo = valores pequeños. Hace falta deflexión FUERTE y sostenida por eje.
- Qué aprendimos: canal de sticks y trama neutra conocidos; falta separar throttle/yaw/pitch/roll.
- Siguiente paso: **re-captura con deflexión máxima y sostenida, UN eje a la vez ~4-5 s, neutro claro entre cada uno** (mantener el stick a fondo, no toques suaves). Con deflexiones grandes, el byte de cada eje saltará sin ambigüedad. Luego: intentar replay/craft de `0x01/0x0a` con dron asegurado sin hélices.
- Análisis: `scratchpad/bursts.py` (localizó 0x01/0x0a), `sticks.py`, `windows.py`.

## 2026-07-12 EXP-005 — Deflexiones fuertes: MAPA DE EJES DECODIFICADO ✅✅
- Estado: [OBSERVED] — ÉXITO TOTAL. Comando de sticks del Neo completamente decodificado.
- Objetivo: mapear throttle/yaw/pitch/roll con deflexiones a fondo, un eje a la vez, orden: IZQ, DER, ATRÁS, ADEL, ARRIBA, ABAJO, GIRO-IZQ, GIRO-DER.
- Setup: phone-only, PCAPdroid VPN. Captura: `Quinta prueba.pcap` (62 MB). 1949 tramas `0x01/0x0a` (41 B).
- Resultado observado — **estructura del comando de sticks**:
  - Trama DUML `cmd_set 0x01 / cmd_id 0x0a`, 41 bytes. Header DUML de 11 B, luego payload; los sticks están **empaquetados como 4 canales de 11 bits little-endian** que arrancan en el **byte 14 de la trama** (= payload[3]).
  - Extracción: `V = int.from_bytes(frame[14:20],'little')`; `canal_k = (V >> (11*k)) & 0x7FF`, k=0..3.
  - **Neutro = 1024; rango 364 (mín) .. 1024 (centro) .. 1684 (máx)** — convención estándar DJI de 11 bits.
  - **MAPA DE EJES (verificado con las 8 maniobras):**
    - `ch0 = ROLL` — izquierda→364, derecha→1684
    - `ch1 = PITCH` — atrás→364, adelante→1684
    - `ch2 = THROTTLE` — abajo→364, arriba→1684
    - `ch3 = YAW` — giro-izq→364, giro-der→1684
  - Trama neutra de referencia (sticks centrados): `552904c902a9efa000010a01 0d0000 04200001084000 0200000655010456087ff8... crc16`. (bytes 14-19 = `00 04 20 00 01 08` → los 4 canales a 1024).
- Interpretación:
  - [OBSERVED] El comando de control de vuelo en tiempo real del Neo por WiFi está **completamente decodificado**: canal DUML, cmd_set/cmd_id, framing, empaquetado de 11 bits, mapa y rango de los 4 ejes. Todo en claro.
  - [INFERRED] Para REPLAY/CRAFT falta replicar: el wrapper de sesión DJI (bytes `XX 80` + contadores antes del 0x55), el seq_num del header DUML, y ambos checksums (CRC-8 cabecera `arr_2A103`/seed 0x77, CRC-16 `calc_pkt55_checksum` seed 0x3692). Todo conocido y disponible en `comm_mkdupc.py`.
- Qué aprendimos: **sabemos exactamente qué bytes poner para "roll/pitch/throttle/yaw = X"**. Es el ingrediente central del control programático.
- Siguiente paso: (1) reversar el wrapper de sesión y el manejo de seq/ack para construir una trama `0x01/0x0a` aceptable; (2) primer intento de **replay** con el dron ASEGURADO y SIN HÉLICES (comando neutro primero, luego un solo eje suave); (3) si acepta, construir emisor Python (base `comm_mkdupc.py`) y exponerlo a ROS 1 (`dji_neo_driver`).
- Análisis: `scratchpad/decode.py` (decodificador de canales), `table.py`, `map.py`, `yaw.py`.

### EXP-005b — Wrapper de sesión reversado (2026-07-12)
El comando `0x01/0x0a` viaja en un UDP de **61 bytes** (puerto teléfono 3288x → dron 9003), con **20 bytes de wrapper** antes del `0x55`:
```
off  campo                     ejemplo (Quinta)     naturaleza
0-1  header/magic              3d 80                CONST
2-3  SESSION ID                4d 6e                *** cambia por conexión ***  (Tercera=a798, Cuarta=b0e6, Quinta=4d6e)
4-5  timestamp rápido (16b LE) 10 96                contador rápido, wrap
6    CONST 0x05                05                   CONST
7    contador                  1d                   incrementa
8-11 timestamp monotónico 32b  f0 95 10 96          SIEMPRE creciente (1948/1948)
12-15 reservado                00 00 00 00          ~cero (b14,b15 CONST 00)
16   contador mod-256          75                   +1 por paquete
17   CONST 0x01                01                   CONST
18-19 CONST 00 00              00 00                CONST
```
Luego 41 bytes de DUML `0x01/0x0a` (header 11B con seq_num en frame[6:8], canales 11-bit en frame[14:20], CRC-16 al final).
- [OBSERVED] El **session ID (off 2-3) es por-conexión** → para inyectar hay que **leerlo en vivo** de la sesión activa, no se hardcodea. Igual los contadores/timestamps: hay que continuarlos desde el estado actual.
- [INFERRED] Existe además una conexión **TCP 6001** que probablemente **negocia/establece la sesión** (de donde sale el session ID). Reversar ese handshake es el prerequisito para que un emisor propio (PC) tenga sesión válida sin depender del teléfono.
- Obstáculo de inyección: enviar UDP a `192.168.2.1:9003` requiere estar en el enlace: (a) emitir desde el teléfono (app/termux/root), o (b) el PC se une a la WiFi del Neo y emite — pero el dron podría rechazar un 2º controlador (conflicto "dos dispositivos"), salvo que el PC establezca su propia sesión (TCP 6001).
- Siguiente paso: analizar el **handshake TCP 6001 + secuencia de conexión** (cómo nace el session ID y los contadores) para decidir la vía de inyección; luego primer replay con dron asegurado sin hélices.

### EXP-005c — Handshake de sesión reversado (2026-07-12): sesión CLIENTE-INICIADA sobre UDP 9003
- [OBSERVED, decisivo] **TCP 6001 NO lleva datos** (0 payload en Tercera/Cuarta/Quinta; solo SYNs, muchos, probablemente reintentos que el dron ignora/RST). TCP 65000 al inicio → **RST**. **La sesión de control NO depende de TCP.** Todo el arranque es UDP 9003.
- Secuencia de arranque (Quinta, primeros paquetes 9003), con tipos de wrapper `XX 80`:
  1. `tel->DRON 30 80 4d6e 000000 93 | 687264006400c00514...` — **HELLO/config; el teléfono ELIGE el session ID `4d6e` y lo anuncia** (mismo formato que el heartbeat `30 80` de EXP-001, con sessID en bytes 2-3).
  2. `DRON->tel 09 80 4d6e 000000 aa 01` — **ACK del dron, ECHA el mismo session ID** (no lo asigna el dron).
  3. `tel->DRON 21 80 4d6e <counters> 55 0d 04 33 02 0e .. 00 01 ..` — serie de comandos DUML de init (`cmd_set 0x00/id 0x01` get-version, `0x00/0xb7`, etc.).
  4. `22 80 4d6e <counters 6872..>` en ambos sentidos — keepalive/sync de contadores (semilla `6872`).
  5. `3d 80 4d6e <counters> 55..01 0a ..` — **stream de control** (sticks) una vez listo/armado.
- [OBSERVED, decisivo para inyección] **El session ID es elegido por el CLIENTE y solo eco-confirmado por el dron.** No hay nada que el dron asigne que no podamos elegir nosotros. La sesión es 100% cliente-iniciada sobre UDP 9003, sin dependencia de TCP.
- Implicación: un emisor propio (PC unido a la WiFi del Neo, teléfono APAGADO para no chocar) puede, en principio: mandar su `30 80 <sessID propio>` hello → recibir el `09 80` ack → reproducir los comandos de init `21 80` → arrancar el stream `3d 80` de control. Falta determinar el subconjunto mínimo de comandos de init que el dron exige antes de aceptar sticks, y las reglas exactas de los contadores/timestamps del wrapper.
- Siguiente paso: (1) mapear la lista mínima de init (qué DUML del paso 3 son imprescindibles); (2) prototipo Python de emisor UDP 9003 (hello+ack+init+control) probado con dron ASEGURADO sin hélices, empezando por hello/ack (sin comandos de vuelo) para validar que el dron nos acepta la sesión.

### EXP-006 — Emisor Fase 0 EJECUTADO: SESIÓN PROPIA ACEPTADA ✅✅✅ (2026-07-12)
- Estado: [OBSERVED] — ÉXITO. Software propio abrió sesión con el Neo.
- Setup: Android **sin root**, **Termux + Python** (el PC NO logró unirse a la WiFi del Neo → se pivoteó a emitir desde el teléfono). Teléfono en WiFi del Neo, DJI Fly cerrado. Script `phase0_hello.py` (hello `30 80` replay session `4d6e`).
- Resultado: **585 respuestas del dron: 10 ACK `09 80` + 558 keepalives `22 80`**, todas con session ID `4d6e` (el nuestro). "EXITO: el dron acepto la sesion".
- Además, downlink con tipos NUEVOS del dron (candidatos a TELEMETRÍA): `4e80 4d6e 000001ec 68726872 ...` y `8980 4d6e 0000012b 68726872 ...` (periódicos). A decodificar (¿batería/actitud/estado?).
- Interpretación: [OBSERVED] **Un emisor propio (Termux, sin root, sin DJI Fly) establece y mantiene una sesión de control con el Neo por UDP 9003.** Confirmado que la sesión es cliente-iniciada y que el dron nos trata como su interlocutor (nos manda keepalives + telemetría). Prueba reproducible del canal de control.
- Siguiente paso: Fase 1 = mantener la sesión viva + decodificar telemetría `4e80/8980` + reproducir el init `21 80` (get-version 0x00/0x01, etc.), SIN comandos de vuelo. Luego Fase 2 (control) SOLO con dron asegurado, SIN HÉLICES y con visto bueno explícito.
- **Análisis del downlink (del pcap Quinta, paquetes completos; Termux solo mostró 16 B):**
  - **Serial del Neo EN CLARO**: `<serial-neo-redactado>` (en `4e80` y `8980`).
  - **`8980`** = stream de telemetría principal: encapsula DUML **`0x51/0x01` (103 B)** = OSD/actitud/batería/estado. Fuente de telemetría para ROS.
  - **`4e80`** = paquete de estado/identidad (serial + contadores).
  - **`c085` = stream de VÍDEO H.264** (37.662 paquetes en el downlink 9003) — el vídeo en vivo viaja por el MISMO canal 9003 de la sesión. Implica que una sesión propia podría recibir control + telemetría + **vídeo** juntos → conecta con el hito original vídeo→SLAM→ROS (decodificar H.264 fragmentado en UDP = trabajo aparte).
  - Downlink usa muchos "tipos" (2º byte 80..85) = probable fragmentación/canal; los consistentes útiles: `2280` keepalive, `4e80` estado, `8980` telemetría, `c085` vídeo.

### EXP-007 — Fase 2a: el dron ACEPTA nuestras tramas de control FORJADAS ✅✅✅ (2026-07-12)
- Estado: [OBSERVED] — ÉXITO. Emisor propio forja y envía control aceptado por el Neo.
- Herramienta: `tools/neo_control/control_sender.py` (Termux). Genera trama DUML `0x01/0x0a` con **canales de 11 bits + CRC-8 (poly refl 0x8c, seed 0x77) + CRC-16 (poly refl 0x8408, seed 0x3692)**, ambos CRC **generados por fórmula** y verificados contra tramas reales. Wrapper `3d 80` con contadores incrementales. Envía **NEUTRO (1024×4)** — no arma ni mueve motores (verificado: neutro no arma en DJI).
- Setup: Android/Termux, teléfono en WiFi del Neo, DJI Fly cerrado, hélices PUESTAS (neutro es seguro). Batería no al 100%.
- Resultado: hello→ACK; **151 tramas de control enviadas; el dron siguió respondiendo todo el tiempo** (763 keepalives, 16 `8980` telemetría, 16 ACK, 9 `4e80`). "sesion VIVA bajo control".
- Interpretación: [OBSERVED] **El Neo acepta tramas de control forjadas por software propio** (CRC/estructura/wrapper correctos). No las rechaza ni cae la sesión. Es el paso previo directo al control real de motores.
- Análisis de batería (2 corridas, distinto nivel): campos que difieren = contadores de sesión (off 95 seq, off 99-101 uptime-ms, off 111-112, off 135-136 crc) → NO batería. **Candidato a batería: `8980` off 105-107** (`92f80c`→`02fc0c`, ~850066 vs ~851970, 32-bit LE), estable dentro de cada corrida y distinto entre baterías. Sin confirmar semántica (voltaje/carga/ID) — requiere test de drenaje controlado.
- Siguiente paso: (1) confirmar el campo de batería con drenaje/niveles conocidos; (2) mapear actitud moviendo el dron a mano (telemetría IMU); (3) test de motores SOLO con dron fijado firme (no en mano) o hélices fuera, con consentimiento explícito.

### EXP-008 — Intento de mapear actitud (IMU) por telemetría: NO en reposo (2026-07-12)
- Estado: [OBSERVED] — actitud no extraíble por ahora.
- Método: logger en Termux manteniendo sesión mientras el usuario inclina el dron a mano (pitch/roll/yaw), buscando bytes que oscilen con el movimiento.
- Resultado: [OBSERVED] Con el dron **quieto y desarmado** solo llegan 4 tipos (`2280,0980,4e80,8980`); NINGÚN byte oscila con las inclinaciones. Los candidatos que marcó el detector (`8980` off 111-112) resultaron **ruido/checksum** (valores saltan por todo 0-65535 sin relación con el movimiento). off 105-107 estable (batería, `0x0cdbf5`≈843765).
- [OBSERVED] En el pcap de vuelo (Quinta), el `8980` es un **contenedor multiplexado**: casi todos los bytes varían 0-255 entre paquetes (distintos sub-mensajes) → no se aísla la actitud por varianza.
- Conclusión: la telemetría rica (actitud) **solo fluye armado/volando** y va multiplexada en `0x51/0x01`; decodificarla requiere el formato OSD interno del Neo (RE profundo) o una suscripción OSD específica. Se APLAZA — no es ruta corta.
- Prioridad real restante: **test de motores** (la prueba física del control) con dron fijado firme/hélices fuera; y confirmar batería (off 105-107).

### EXP-009 — Fase 2b intento CSC (armado por sticks) a throttle-min: SIN respuesta de motores (2026-07-12)
- Estado: [OBSERVED] — resultado nulo (seguro y válido).
- Setup: Termux, sesión propia viva, dron FIJADO CON CINTA, hélices PUESTAS, batería no llena. Script `arm_test.py`: baseline throttle-min → 3 s de "CSC" (roll=364,pitch=364,thr=364,yaw=1684) → soltar.
- Resultado: **no se movió ninguna hélice** en ninguna dirección de la combinación.
- Interpretación: [INFERRED] (1) el Neo probablemente **no arma por CSC** (dron de despegue automático, sin combinación de sticks clásica); y/o (2) el combo enviado no era una CSC estándar (una CSC real suele ser **ambos sticks hacia adentro o ambos hacia afuera**, no thr-min + yaw-max); y/o (3) falta el **init** que hace DJI Fly antes de volar.
- Siguiente paso: path B — replicar el **comando de despegue real** extraído del pcap, con hélices FUERA.

### EXP-010 — Comando de DESPEGUE identificado desde el pcap de vuelo ✅ (2026-07-12)
- Estado: [OBSERVED] — comando aislado y validado por CRC.
- Método: extractor `scratchpad/extract_takeoff.py` (parser pcap RAW-IP linktype 101 + escáner DUML/CRC) sobre `Quinta prueba.pcap`. Se listaron todos los comandos discretos uplink y su timeline respecto al arranque del stream de sticks `0x01/0x0a` (= instante de despegue).
- Resultado observado:
  - **Comando de despegue = DUML `cmd_set 0x03 / cmd_id 0xda`, ÚNICO en todo el vuelo**, disparado ~60 ms ANTES de que arrancara el stream de sticks. Trama completa: `551204c7020319e64003da05ffffffff6445` (18 B). sender=0x02, **receptor=0x03 (controladora de vuelo)**, payload = `05 ff ff ff ff`. CRC-8 hdr=0xc7 ✅ y CRC-16=0x4564 ✅ verificados y reproducibles con nuestras funciones (seq recomputable).
  - `0x03/0x20` (flyc) es **periódico ~1 Hz** (no es el trigger); su payload cambia de estado `02 0000..` (pre-vuelo) a `03 0e4686..` (en vuelo) — candidato a comando continuo de modo/autoridad de vuelo que quizá deba acompañar al despegue.
  - Confirmado patrón del wrapper: **byte0 = longitud total del paquete UDP** (keepalive 34=0x22, control 61=0x3d, despegue 38=0x26).
  - No se halló un comando de "aterrizaje" discreto simétrico; el aterrizaje del Neo probablemente es por descenso de throttle/auto-land o va tunelizado en el contenedor `0x51/0x01`. **Implicación de seguridad: el corte fiable NO es el software sino el botón de encendido del dron.**
- Interpretación: [INFERRED con alta confianza] `0x03/0xda 05 ffffffff` es el despegue automático ("one-tap takeoff") del Neo.
- Siguiente paso: forjar e inyectar ese comando con dron FIJADO y **hélices FUERA**, botón de apagado como corte de emergencia. Herramienta: `tools/neo_control/arm_takeoff.py` (gated).

### EXP-011 — Init + autoridad 0x03/0x20 + despegue: el dron RESPONDE con su tono de pre-despegue ✅ (2026-07-12)
- Estado: [OBSERVED] — avance mayor. Comando de despegue ACEPTADO por la controladora (reacción audible); motores no giran.
- Setup: Termux, sesión propia, dron FIJADO, **hélices FUERA**, botón de apagado a mano. Script `init_takeoff.py` / `despegue.py` (base64) = hello → init verbatim (0x00/0x01 ×3, 0x00/0xb7, 0x11/0x4a, 0x00/0x51, 0x07/0x93, 0x51/0x34, 0x18/0x37, 0x18/0x3c) → stream sticks NEUTRO + autoridad `0x03/0x20` (estado 02→03) → `--fire` dispara `0x03/0xda` ×3.
- Resultado observado: **el dron emitió el sonido/tono que SIEMPRE hace justo antes de despegar** (tono de armado/pre-despegue). NINGUNA hélice giró. (Salida de `respuestas`/`tel8980` pendiente de pegar por el usuario.)
- Interpretación:
  - [OBSERVED, decisivo] Con init + autoridad, el `0x03/0xda` forjado **es aceptado y entendido por la controladora de vuelo**: el dron arranca su secuencia de armado (tono). En EXP-007/EXP-009/primer intento de EXP-010 (sin init) hubo SILENCIO total → el init/autoridad fue el ingrediente que faltaba.
  - [INFERRED, alta confianza] Motores no giran = **parada de seguridad por falta de hélices** (los ESC detectan ausencia de carga/hélice en el auto-test de arranque y abortan tras el tono). No es fallo del comando.
- Qué aprendimos: **control programático a nivel de COMANDO DE VUELO logrado** — nuestro software dispara la lógica de despegue del Neo. El giro real de motores está gateado por el chequeo de hélices del propio dron.
- Siguiente paso: (1) capturar el downlink durante el fire para confirmar el cambio de estado (respuesta a `0x03/0xda`, telemetría `8980`); (2) decidir prueba de giro real: requiere hélices puestas + fijación tipo jaula/caja cerrada (riesgo físico real) — solo con procedimiento de seguridad reforzado y consentimiento explícito.

### EXP-012 — Captura PCAPdroid del intento de despegue (`Sexta prueba.pcap`): el dron NO envía flyc OSD a nuestra sesión (2026-07-12)
- Estado: [OBSERVED] — diagnóstico: no hay código de rechazo legible por esta vía.
- Setup: PCAPdroid VPN capturando mientras `despegue.py fire` (init+autoridad+takeoff). Hélices PUESTAS (aclarado por el usuario: estuvieron puestas TODO el tiempo), dron fijado. `Sexta prueba.pcap` (233 KB).
- Resultado observado:
  - Nuestro `0x03/0xda` (takeoff) **salió 3 veces** (t=22.0, wrapper `2680`). Uplink = sticks `3d80` ×310 + hello `3080` ×29 + takeoff ×3.
  - **Downlink del dron: SOLO `2280` keepalive (×2363), `8980` (`0x51/0x01` status ×48), `4e80` (×25→`0x07/0x94` beacon), `0980` ACK (×29).** NO video `c085`, NO OSD de vuelo, **NINGUNA respuesta `0x03`** de la controladora al takeoff.
  - `0x51/0x01` (status) pre vs post-takeoff: TODO lo que cambia son contadores/CRC. **Cero cambio de estado de vuelo.** `0x07/0x94` = beacon serial+contador, invariante al takeoff.
- Interpretación:
  - [OBSERVED] La sesión propia recibe un heartbeat de estado mínimo, **no el OSD de vuelo**. El dron acepta comandos y reacciona (tono, EXP-011) pero **no nos transmite estado de vuelo ni motivo de rechazo**. Probablemente falta una **suscripción de datos** (la app la envía) o el OSD rico solo fluye volando.
  - [INFERRED] Como con hélices puestas + comando válido + tono + sin giro y sin código, el bloqueo es una **precondición de vuelo del propio dron** (candidato fuerte: fijado con cinta → sensores de visión/IR de abajo ven la superficie / dron constreñido → aborto de seguridad tras el tono) o el dron no alcanza el estado "listo" real (nuestro init es one-shot; la app lo streamea continuo y el dron transiciona `0x03/0x20` 02→03 tras sus chequeos).
- Idea del usuario: **modo de vuelo** (¿manual?). Plausible, pero el init replicado ya incluye los comandos de modo/config (`0x18/0x37`, `0x18/0x3c`) del vuelo real → el modo probablemente ya está puesto; sospechoso mayor = precondición física.
- Siguiente paso: prueba decisiva y SEGURA = **hélices FUERA + dron LIBRE** (no pegado, sensores despejados) + `fire`. Con hélices fuera no hay empuje aunque gire; si con el dron libre los motores giran → confirmado que el bloqueo era la restricción/sensores y el control es total. (Requiere poder quitar hélices — pendiente de confirmar con el usuario.) Alternativa software: identificar el comando de suscripción de telemetría para que el dron nos mande el motivo.

### EXP-013 — Telemetría y vídeo están GATED a volar; plan de vuelo supervisado (2026-07-12)
- Estado: [OBSERVED] + [PLAN].
- Hallazgos del pcap Quinta:
  - **En tierra (t<16.3) el dron SOLO manda `0x51/0x01` + `0x07/0x94`** — lo mismo que ya recibe nuestra sesión. La telemetría rica (`0x23/*`, `0x03/0xd7` actitud, `0x0a/*`) y el **vídeo (`0xc0`, 1472 B ×37k)** arrancan TODOS en t=16.3-16.5 = **al despegar**. No falta comando de suscripción; el OSD/vídeo está atado al vuelo.
  - Aterrizaje: **no hay comando de auto-land aislado**; el throttle se quedó neutro (1024) al final → aterrizó por auto-land tunelizado o el pcap cortó. `0x03/0xda` tiene subcomandos: `05 ffffffff` (armado/despegue, ×4), `0x0d ...` (stream de control en vuelo, ×99), `0x08`, `0x07`, `0x0a`.
- Decisión del usuario: **vuelo supervisado al aire libre** (nuestro software ordena el vuelo). Condiciones confirmadas por el usuario: **padre supervisando + failsafe=Aterrizar + espacio abierto exterior + acepta riesgo al dron**.
- Método de aterrizaje (sin comando dedicado confiable): **throttle-min sostenido vía sticks** (ch2=364) + redes: failsafe=Land al matar el script, auto-land por batería baja, hover-GPS (no fly-away).
- Plan vuelo #1 (mínimo): hello→init→autoridad→takeoff `0x03/0xda`→hover neutro ~4s→land throttle-min ~10s. SIN movimientos. Herramienta: `tools/neo_control/flight1.py` (modo `fly` gated; Ctrl+C = aterrizar).
- Siguiente: ejecutar vuelo #1 supervisado; si controla takeoff+land, capturar de paso vídeo+telemetría (que ya fluirán al volar) para el pipeline ROS. Luego añadir movimiento.

### EXP-014 — CONTROL DESDE LA PC (WiFi directo) ✅ (2026-07-13)
- Estado: [OBSERVED] — ÉXITO. La PC se une al WiFi del Neo y controla; se abandona la dependencia de Termux/base64.
- Contexto: pasar scripts al teléfono por pegado en Termux corrompía archivos largos (aun en base64/76-col). Se pivotó a **correr todo en la PC**.
- PC: adaptador **Qualcomm WCN685x Wi-Fi 6E DBS**; Python 3.14.5. El intento previo "PC no se une al Neo" se resolvió: (1) **el teléfono debía estar DESCONECTADO del Neo** (acepta un solo cliente → si el móvil está, rechaza el handshake WPA2: estado `asociando`→`desconectado`); (2) poner los perfiles de casa (`<red-casa>*`) en `connectionmode=manual` para que Windows no saltara de vuelta por "sin internet".
- Herramienta: **`scratchpad/run_neo.ps1 -mode "<fly|>"`**: pone <red-casa> en manual → conecta `DJI-NEO-XXXX` (perfil WPA2PSK/AES creado con la pass del usuario) reintentando hasta obtener IP `192.168.2.x` → corre `vuelo.py` → **finally**: restaura <red-casa> a auto y reconecta (Claude recupera internet y ve la salida). Perfil WiFi ya guardado en el adaptador.
- Resultado: SSID=`DJI-NEO-XXXX`, IP local `192.168.2.188`, **`vuelo.py` (dry run) → `hello -> ACK`, sesión viva**. Internet restaurado al final.
- Archivo de vuelo: **`vuelo.py`** en la raíz del proyecto (md5 `0bddac82790b2a142182528cd63b9e4f`). Modos: sin arg = DRY RUN (no despega); `fly` = despegue→hover→aterrizaje (throttle-min). Log de cada corrida en `neo_run.log`.
- Pendiente: saber si la PC es laptop (para vuelo exterior con la PC cerca del dron) o de escritorio (vuelo en alcance WiFi, patio). El vuelo real `fly` SOLO exterior + padre + failsafe.

### EXP-015 — Validación del tono desde la PC: NO arma (2026-07-13)
- Estado: [OBSERVED] — el armado NO es reproducible desde la PC.
- `tone_test.py` (init+autoridad+takeoff×3) y `tone_test2.py` (streaming COMPLETO: init rotando + `0x51/0x01` CV51 a ~33 Hz + autoridad + **despegue sostenido 6 Hz** + throttle-down), ambos vía `run_neo.ps1`. Dron ASEGURADO (taped), hélices puestas, teléfono fuera del Neo.
- Resultado: ambos corren limpios desde la PC (`hello->ACK`, sesión viva), pero **el dron no hizo NADA — ni tono ni motores.** (El único tono confirmado sigue siendo EXP-011, en teléfono, 1 de N.)
- Interpretación (hipótesis, sin confirmar):
  - [INFERRED] El armado depende de una precondición que no cumplimos de forma estable: probablemente **estado/autorización de sesión** (replicamos SIEMPRE la sesión vieja `4d6e` + UUID viejo `2020ee4d-...` en init/`0x07/0x93`/`0x51/0x34`/CV51; la app genera sesión+UUID frescos por conexión y la autorización de vuelo podría atarse a eso), y/o **precondición física** (dron fijado/constreñido o sensores tapados → seguridad rehúsa armar), y/o requiere **autorización previa de DJI Fly en ese arranque**.
  - [OBSERVED] Indoors + taped no permite validar/forzar el armado de forma segura (si funcionara, despegaría dentro).
- Conclusión: se agotó la vía de validación indoor. El armado real solo se puede probar de forma segura **al aire libre, dron LIBRE, con GPS** (el vuelo supervisado planeado). Alternativa de RE profunda: reversar el handshake de sesión/UUID fresco para ser controlador "plenamente autorizado".

### EXP-016 — COMANDO DE MODO DE VUELO descubierto (intuición del usuario) ✅ (2026-07-13)
- Estado: [OBSERVED] — el set-modo estaba entre los comandos que NO replicábamos. Fuerte candidato al ingrediente faltante para armar.
- Método: captura `Septima prueba.pcap` (25 MB, phone+PCAPdroid) cambiando de modo cada ~5 s: Seguimiento→Dronie→Órbita→Cohete→Spotlight→Control manual. Análisis del mux `0x51/0x01` desanidado.
- Resultado: **el switch de modo = DUML `cmd_set 0x03 / cmd_id 0xf9`, payload `878867a3 <MODO> 000000`**, uno por cambio (t=14.4/21.8/28.8/34.4/39.8):
  - `04`=Dronie, `05`=Órbita, `06`=Cohete, `01`=Spotlight, **`09`=Control MANUAL**.
  - Trama manual completa: `551504a90217e4d24003f9878867a3090000003d10` (crc8/crc16 verificados; header `55 15 04 a9`, sender `02`, recv `17`).
  - **`878867a3` es FIJO del dron** (aparece 64× también en Quinta, otra sesión) → hardcodeable.
  - El UUID `2020ee4d-6aca-466f-...` es el MISMO que ya usábamos → NO era el problema; el problema era el MODO.
- Sesión fresca observada: `fc10` (no necesaria: el UUID/878867a3 son estables).
- Herramienta: `tone_test3.py` = streaming completo (v2) + **set MODO MANUAL 0x09 repetido** antes/durante el settle, luego despegue sostenido. Builder `modecmd(seq,0x09)` validado.
- Siguiente: correr `tone_test3.py` con dron ASEGURADO (ahora podría SÍ armar/girar → riesgo real indoor).
- **RESULTADO EXP-016 (2026-07-13): el set-modo TAMPOCO surte efecto — el dron NO cambia de modo, ni tono ni motores.**

### EXP-017 — DIAGNÓSTICO CLAVE: el dron ACEPTA la sesión pero IGNORA todos nuestros comandos (2026-07-13)
- Estado: [OBSERVED, decisivo] — replanteamiento del bloqueo.
- Evidencia acumulada: con sesión propia (ACK + keepalives + telemetría OK), el dron **no ejecuta NINGÚN comando forjado**: ni `0x03/0xf9` set-modo (el modo NO cambia), ni `0x03/0xda` takeoff (salvo la anomalía única EXP-011), ni se ha confirmado NUNCA respuesta a sticks `0x01/0x0a`. Todos con CRC/estructura válidos.
- [INFERRED, alta confianza] El bloqueo NO es el modo, ni la precondición física, ni el UUID. Es **AUTORIDAD DE COMANDO**: el dron distingue entre "cliente conectado" y "controlador autorizado". Nuestra sesión abre (hello→ack) pero no obtiene autoridad para que se ejecuten comandos. Candidatos a lo que falta: (a) handshake interactivo de init (get-version→respuesta→…) que otorga autoridad y que nosotros disparamos sin procesar respuestas; (b) semántica de los **contadores del wrapper** (ts-fast, ts-monótono, contador mod-256) que el dron valida como ventana de sesión y que generamos sintéticos/fuera de rango; (c) seq_num DUML / protección anti-replay; (d) binding/activación del controlador.
- Consecuencia importante: el **vuelo exterior probablemente TAMBIÉN fallaría** (la ejecución de comandos no depende de estar libre/GPS) → no arriesgar el vuelo hasta resolver la autoridad.
- Siguiente (en sesión fresca, no de madrugada): **comparación byte a byte de NUESTRO uplink vs el de la app** (mismo arranque), enfocada en: secuencia exacta de establecimiento de sesión, valores/relación de los contadores del wrapper tras el ack, y seq_num DUML. Objetivo: reproducir la autoridad de comando.

### EXP-006-orig (nota) — Emisor Fase 0 (diseño previo)
- Herramienta creada: **`tools/neo_control/phase0_hello.py`** (Python, sin dependencias). Envía el hello `30 80` (session `4d6e` replay, o aleatorio con `--new-session`) a `192.168.2.1:9003` y escucha el ACK `09 80` / keepalives `22 80` del dron. NO envía comandos de vuelo.
- Bytes de referencia (Quinta): HELLO=`30804d6e00000093687264006400c005140000640000019001c005140000640014006400c00514000064000101040102`; ACK del dron=`09804d6e000000aa01`; luego keepalives `22 80 4d6e ...6872...`.
- Secuencia de init observada (tel→dron tras el hello): ráfagas de `0x00/0x01` (get-version, DUML len13), algún `0x00/0xb7` (len18), un `0x11/0x4a` (len34), intercalados con keepalives `22 80` a ~50 Hz. El stream de control `3d 80`(0x01/0x0a) NO aparece hasta armar/despegar.
- Setup para ejecutar: PC unido a la WiFi del Neo (dron 192.168.2.1), **teléfono apagado**, dron asegurado SIN hélices. Criterio de éxito: el dron responde `09 80`/`22 80` con nuestro session ID → sesión aceptada desde el PC.


### EXP-018 — REINTERPRETACION DEL WRAPPER: era el protocolo UDP fiable de samuelsadok/dji_protocol; nuestros comandos iban malformados ✅✅✅ (2026-07-13)
- Estado: [OBSERVED, DECISIVO] — reanalisis desde cero de los pcaps con la hipotesis `samuelsadok/dji_protocol` (`udp_protocol.md`). **Refuta la hipotesis de "autoridad de comando" (EXP-017).**
- Metodo: parser propio del protocolo UDP DJI (`scratchpad/djiudp.py`) aplicado a `Septima` (app cambia de modo), `Quinta` (vuelo real app) y `Sexta` (nuestra sesion, comandos ignorados). Validacion constructiva: reconstruir byte-a-byte los type-5 reales (`validate_fix.py`).
- **Los 20 bytes del "wrapper" NO eran timestamp+contador. Son la cabecera del protocolo UDP fiable de DJI:**
  - `0x00-01` longitud (bits14:0) | bit15=1  ·  `0x02-03` session id  ·  `0x04-05` **numero de secuencia**  ·  `0x06` **tipo de paquete** (0x00..0x06)  ·  `0x07` **XOR de los bytes 0..6** (checksum de cabecera).
  - Type-5 (comandos app->dron) sigue con: `0x08-09` send-window start · `0x0a-0b` send-window end · `0x0c-0f` resend state 1/2 · `0x10` contador type-5 · `0x11-13` `01 00 00` · `0x14+` payload DJI MB (0x55...).
- **Validacion (adversarial, 3 sesiones):**
  - App (Septima+Quinta): **`0x07 = XOR(bytes 0..6)` en el 100% de 89.000+ paquetes, todos los tipos, 0 fallos.** Tipos observados: 0x00 hello, 0x01 telemetria (DN), 0x02 video (DN), 0x04 ACK (UP), 0x05 comandos (UP).
  - **Seq type-5 arranca en seed+8 y avanza +8.** El HELLO lleva el seed en `0x08-09` (el nuestro = `0x7268`). Quinta: primer comando `0x7270`, pasos +8, exacto.
  - **Reconstruccion:** con el wrapper corregido se regeneran **8/8** paquetes type-5 reales de Quinta identicos byte a byte.
- **Nuestro emisor (Sexta) divergia en TRES campos a la vez:**
  1. `0x07`: escribiamos `n&0xff` (contador) en vez del XOR -> **311 de 313 comandos con checksum de cabecera INVALIDO** (2 pasaron por coincidencia).
  2. `0x04-05` seq: arrancabamos en `0x9600` paso +0x20 (32); lo correcto era `0x7270` paso +8 -> **cada comando caia FUERA de la ventana RX del dron**.
  3. `0x08-13`: metiamos un falso "tsmono" como send-window (basura `0x0000/0x0010...`) en vez de start/end coherentes.
- **PRUEBA IRREFUTABLE (ventana RX que reporta el propio dron, offset 0x18-0x1b de sus type-1):**
  - Quinta (app): la ventana RX type-5 **AVANZA** `0x7268 -> 0x7288 -> 0x72b0...` = el dron consume los comandos.
  - Sexta (nosotros): la ventana RX type-5 **CONGELADA en 0x7268 para siempre** = el dron **no acepto NI UN comando nuestro**.
- Interpretacion: [OBSERVED] El bloqueo NO es autoridad/autenticacion. El dron descarta nuestros comandos en la capa de UDP fiable por **cabecera XOR invalida + seq fuera de ventana + campos de flow-control con basura**, antes de llegar a la capa DUML/vuelo. La sesion sigue viva porque el HELLO (type-0) si es correcto (lo replicamos literal) y lo re-enviamos como keepalive. La anomalia del tono unico (EXP-011) encaja: de ~313 paquetes, 2 pasaron el XOR por azar -> algun comando pudo colarse una vez.
- **Correccion de registro:** quedan INVALIDADAS las interpretaciones de `wrap()`/`f20()` en EXP-006..017 (offset 4-5 "tsfast" y 8-11 "tsmono" eran secuencia y ventanas). La conclusion de "autoridad de comando" (EXP-017) se abandona.
- Cambio de codigo: nuevo modulo **`tools/neo_control/neo_udp.py`** (builder correcto, validado 8/8 y reproduce el frame de modo verbatim) + **`tools/neo_control/set_mode.py`** (prueba segura: manda modo Manual 0x09 con wrapper correcto y confirma exito viendo AVANZAR la ventana RX del dron; sin motores).
- Siguiente (seguro, sin vuelo): correr `set_mode.py` con el Neo encendido y la PC en su WiFi. Exito = la ventana RX type-5 avanza sobre 0x7270 (aceptacion a nivel transporte) y/o el modo cambia en telemetria. Solo tras reproducir el estado type-5 de la app se plantea cualquier prueba fisica con motores.

- **RESULTADO EN HARDWARE (2026-07-13, `set_mode.py` desde la PC):** ✅✅✅ **el Neo ACEPTA por primera vez comandos forjados por software propio a nivel de transporte.** Baseline ventana RX type-5 = `0x7268` (congelada, = seed). Tras enviar **90 comandos** de modo Manual (seq `0x7270`..`0x7538`, paso +8, XOR correcto), la ventana RX del dron **avanzó a `0x7538`**, siguiendo TODOS nuestros comandos. Confirma EXP-018 en hardware: el bloqueo era el wrapper mal forjado, no autoridad/autenticación. Pendiente menor: confirmar si el flight controller aplicó el modo (la telemetría minima a nuestra sesion no expone el modo; requiere observacion visual o captura del downlink). Hito de transporte LOGRADO: nuestros comandos entran al pipeline del dron.


### EXP-019 — CAPTURA DE DESPEGUE REAL EN MANUAL: el comando es correcto; el candado es el canal de control firmado por sesion (2026-07-13)
> **[CORREGIDO EN EXP-024]** — FALSO: `0x03/0xda 05ffffffff` NO es el despegue (es Detection/SetSwitch, housekeeping). El despegue real es FunctionControl `0x03/0x2a:01` AUTO_FLY. Tampoco hay "canal firmado por sesion" (ver EXP-020). Lo unico que se sostiene de aqui: el modo `0x03/0xf9` ejecuta en el FC.
- Estado: [OBSERVED, DECISIVO] — con el fix de transporte de EXP-018, el **modo** (0x03/0xf9) ejecuta en hardware pero el **despegue no**. El usuario capturo un despegue real en Manual desde DJI Fly ("Octava prueba"): app -> modo Manual -> mantener boton de despegue ~3 s -> hover 5 s -> aterrizaje. Comparado contra "Quinta" (otro despegue real).
- Herramienta nueva: **`tools/neo_control/analysis/unwrap.py`** — des-envuelve el contenedor 0x51/0x01 y saca el censo/timeline REAL de los frames DUML internos (el censo anterior estaba ciego: solo veia el contenedor exterior). Complementos: `duml_timeline.py`, `duml_events.py`, `raw_dump.py`.
- **Estructura del contenedor "transmision transparente" 0x51/0x01** (descubierta): `55 len ver crc8 | snd=3b rcv=e9 | dseq2 | attr=00 | 51 01 | <FRAME DUML INTERNO> | cola~21B (0099d4ac02 <ctr4> ffffffff 0182 00..) | crc16`. El frame interno es el comando real, con su propio snd=0x02/rcv=0x03.
- **El comando de DESPEGUE es `cmd_set=0x03 / cmd_id=0xda`, payload `05 ffffffff`** (subtipo por 1er byte: 0x05=armar/despegar). Aparece 2 veces (t+9.05 y t+38.9). Nuestro `flight.py` ya lo construia byte-identico (`mb_frame(0x02,0x03,dseq,0x40,0x03,0xda,b"\x05\xff\xff\xff\xff")`). **El comando NUNCA fue el problema.**
  - Otros subtipos de 0xda: `0d ...` = heartbeat de flyctrl ~1 Hz durante todo el vuelo; `08`, `0a01`, `07 <id>` = fases del arranque.
- **El envoltorio 0x51/0x01 NO es el candado:** el mismo `05ffffffff` se envio **crudo en Quinta** y **envuelto en Octava**. Los comandos cmd_set 0x03 (flyctrl) tienden a ir envueltos y los sticks (0x01/0x0a) crudos, pero el despegue va de las dos formas.
- **EL CANDADO REAL — canal de control firmado/cifrado por sesion:**
  - **Autoridad `0x03/0x20`:** arranca con variante `02` (token en ceros, = lo unico que enviamos nosotros) y a t+4 cambia a variante `03` con un **token de 8 B distinto por sesion** (Octava `f2458601ac9a06fa`, Quinta `0e468601049b06fa`; estructura `XXXX8601 XXXX06fa`).
  - **Stream `0x03/0xf8`:** primeros payloads constantes (`0b163bde0b163bdf0b163be0`), luego **bloques de 32/64 B que se ven cifrados** (a rcv=0x17), con sub-bloques compartidos entre sesiones (patron tipo ECB) pero contenido divergente. Intercambio UP+DN alrededor de t+10 (reto/respuesta con el dron).
  - **Heartbeat `0x03/0xd7`** (620x, `0104…`+contador incremental) corre continuo durante el vuelo. Nunca lo enviamos.
- **Feasibilidad (medida, no supuesta):** busqueda del token `f2458601ac9a06fa` en el pcap -> **16 ocurrencias, TODAS en uplink (app->dron), 0 en downlink.** El dron no nos entrega el token en claro; la app lo genera/deriva. => (a) si el dron lo acepta como nonce libre, es reproducible; (b) si lo valida contra firma con secreto de dispositivo, es **bloqueo duro** (coherente con el DUML firmado de la generacion 2024, IMaH v2 / secure element). **Un replay estatico del pcap NO armara** porque estos payloads cambian por sesion.
- Diferencia adicional detectada en `flight.py`: nuestra autoridad usa solo la variante `02`; falta la `03` con token, `0x03/0xf8` y `0x03/0xd7`.
- **Siguiente (decisorio, sin vuelo primero):** decodificar el DOWNLINK DUML del dron (contenido de sus type-1/type-2, no solo la ventana RX) para ver si en algun momento concede autoridad o entrega material para el token. Si el token resulta ser un nonce libre -> construir autoridad variante-03 + heartbeat 0x03/0xd7 y probar en vuelo (gated, exterior/espacio amplio supervisado). Si es firma -> el frente se traslada al APK (extraer el algoritmo de firma de `dji.go.v5`), como ya anticipa la "segunda via" de FINDINGS.


### EXP-020 — DOWNLINK DECODIFICADO: no hay cripto en el armado (token = coordenada GPS; 0x03/0xf8 = lote de parametros) (2026-07-13)
- Estado: [OBSERVED, DECISIVO] — a peticion del usuario (sin vuelo): decodificar el downlink DUML del dron y decidir si el "token" de autoridad es reproducible o si toca ir al APK. Resultado: **reproducible, sin firma.**
- Herramienta nueva: **`tools/neo_control/analysis/downlink.py`** — escanea TODO el trafico (UP+DN) buscando frames 0x55 con **CRC-8 de cabecera valido** (independiente del offset del transporte), extrayendo asi las RESPUESTAS del dron. El dron responde en type-1: 0x03/0xd7 (3042), 0x03/0xf8 (154), 0x03/0x20 (35), 0x03/0xda (39), etc.
- **`0x03/0xf8` NO es reto-respuesta cifrado — es GET/SUBSCRIBE de parametros por lotes.** UP: la app manda una lista de valores de 4 B (hashes de nombre de parametro): `bcc37a40 913d177a 196dce7e 8a237103 …`. DN (`snd=03 rcv=02 attr=80`): devuelve los MISMOS valores con un codigo de estado intercalado: `00 bcc37a40 00 913d177a 06 196dce7e 00 …`. Los "bloques cifrados de 32/64 B" de #12/EXP-019 eran arrays de param-hashes + status, no criptografia.
- **El "token" de `0x03/0x20` variante-03 es la COORDENADA GPS del dron (grados×10⁶), no una firma.** Payload = `03 | A(4B lat) | B(4B lon) | contador(4B)`. A/B son FIJOS dentro de la sesion (solo cambia el contador). 4 muestras independientes (Tercer/Cuarta/Quinta/Octava): **A varia solo ±224 y B solo ±140** sobre una base fija (~±0.0002° ≈ ±22 m = jitter de GPS de consumo), y decodifican a una **coordenada geografica real y estable** de la zona del usuario (**valor absoluto redactado por privacidad — NO se versiona**). Una firma criptografica seria uniforme en 32 bits; esta agrupacion fisico-geografica la descarta. El dron reporta posicion en grados×10⁷ en su telemetria (hits DN) => legible/derivable en vivo.
- **La transicion autoridad 02→03** ocurre a ~t+4 s en las 4 capturas (cuando la app ya tiene una posicion de referencia). Variante 02 = A=B=0 (autoridad sin referencia); variante 03 = A/B con la coordenada. La transicion NO depende de ningun valor del downlink previo (el token no aparece en DN en ningun endianness).
- **Conclusion / correccion de #12/EXP-019:** el armado del Neo **NO exhibe canal firmado/cifrado** en las capturas. Los dos sospechosos (envoltorio 0x51/0x01, "handshake" 0x03/0xf8) y el "token" quedan explicados sin secretos. Por que fallaba `flight.py`: mandaba autoridad **solo variante-02** (coordenada en ceros), y omitia el heartbeat `0x03/0xd7`, el lote de parametros y la rafaga de init del despegue — todo reproducible.
- **NO se necesita el APK para esta via.** Siguiente (cuando el usuario lo decida, gated y supervisado): construir en `flight.py` (a) autoridad variante-03 con coordenada (leida de telemetria o plausible), (b) heartbeat `0x03/0xd7` continuo, (c) la rafaga de init del despegue observada, y probar el armado en vuelo. Riesgo fisico real => solo con las precauciones de seguridad ya acordadas.


### EXP-021 — SECUENCIA DE ARMADO COMPLETA, REPRODUCIDA Y VALIDADA BYTE A BYTE (sin hardware aun) (2026-07-13)
> **[CORREGIDO EN EXP-024]** — La "secuencia de armado" reproducida (0x03/0xda, 0x03/0xf8, 0x03/0x34, 0x03/0x3c, 0x0d/0x03, 0x03/0xd7) era en realidad **Detection + GETs + suscripciones (housekeeping)**, NO el armado. El despegue (FunctionControl `0x03/0x2a`) nunca se incluyo aqui. Las validaciones byte-a-byte siguen siendo correctas; lo erroneo era la INTERPRETACION de que esto armaba.
- Estado: [OBSERVED] — todos los builders del armado reconstruyen el trafico real de la app; falta la prueba en dron.
- Objetivo (fijado por el usuario): reproducir fielmente `HELLO -> reliable-UDP -> init -> 0x03/0xf8 -> 0x03/0x20 var-03 -> 0x03/0xd7 -> modo Manual -> 0x03/0xda -> sticks neutros -> aterrizaje`, validando byte a byte contra Quinta y Octava antes de tocar hardware.
- **Dos correcciones de EXP-019/020 (via `analysis/unwrap.py`, censo interno des-envuelto):**
  1. **`0x03/0xd7` es BIDIRECCIONAL.** El dron lo manda en DOWNLINK (3042×, telemetria de actitud) y la app en UPLINK (620×) como heartbeat de control — pero el uplink **arranca en t+9.65, DESPUES del despegue (t+9.05)**, no antes. No es precondicion del armado; es el latido de control ya en vuelo. (EXP-019/020 lo listaban como pieza previa; era mala atribucion — mi primer escaneo plano no lo veia porque va envuelto en 0x51/0x01.)
  2. **El "contador" de la autoridad `0x03/0x20` es un timestamp Unix en segundos.** Quinta `0x6a543b60`, Octava `0x6a55629e` decodifican a fechas de 2026 (difieren ~21 h); +1 por envio a 1 Hz. => al forjar se usa la hora real (`int(time.time())`), no un valor viejo hardcodeado.
- **Estructura decodificada de cada pieza (todas validadas):**
  - Autoridad `0x03/0x20`: `<var:1> <lat:int32 LE> <lon:int32 LE> <ts:uint32 LE>`. var-02 => lat/lon=0; var-03 => coordenada en grados×1e6. rcv=0x03, attr=0x40.
  - Heartbeat `0x03/0xd7`: 1er frame `01010000`; resto `01040000`+`uint32 LE` contador incremental. attr=0x80.
  - Lote `0x03/0xf8`: 1er batch constante `0b163bde 0b163bdf 0b163be0` (IDs de parametro). rcv=0x03.
  - Rafaga de armado (junto al `0x03/0xda`): `0x03/0x34` (vacio), `0x03/0x3c` (vacio), `0x0d/0x03` (`00000000`, rcv=0x0b).
  - Despegue `0x03/0xda`: `05 ffffffff`. Va **crudo** en Quinta y envuelto en Octava (el envoltorio NO es candado). Nuestro emisor lo manda crudo (como Quinta, vuelo confirmado).
- **VALIDACION (nuevo `analysis/validate_arm.py`, adversarial contra 2 sesiones):**
  - Reconstruccion generica MB (CRC-8 cabecera + CRC-16): **Quinta 7108/7108** y **Octava 3197/3197** frames UP identicos byte a byte.
  - Builders semanticos: **11/11 OK en Quinta Y en Octava** (modo, autoridad var-02 y var-03, heartbeat init y con contador, lote 0x03/0xf8, despegue, rafaga 0x34/0x3c/0d03).
  - Privacidad: el validador extrae lat/lon del frame real solo para alimentar el builder y comparar; **nunca los imprime**.
- **Cambios de codigo:**
  - `neo_udp.py`: builders nuevos `authority_frame` (var-02/03 con ts-unix), `d7_frame`, `f8_frame`, `arm34/arm3c/arm0d03_frame`, `takeoff_frame`. Todos bare (snd=0x02), con rcv/attr correctos.
  - `flight.py` reescrito: secuencia completa. **DRY (por defecto) ejecuta TODO menos el despegue** (init + autoridad + 0x03/0xf8 + rafaga + modo + heartbeat + neutro) => prueba segura de que el dron ACEPTA cada frame (ventana RX avanza) sin armar. `--fly --armed-ok` añade el despegue. Coordenada var-03 por CLI `--lat/--lon` (NO hardcodeada; sin ellas => var-02 con aviso).
  - Autotest offline: los 7 tipos de frame + la rafaga construyen con CRC valido.
- **Incognitas que solo resuelve el hardware (no mas analisis de escritorio):**
  - Si el armado exige var-03 con coordenada REAL o acepta cualquiera/zeros (EXP-020 la describe como dato posicional, no firma => quiza no se valida).
  - Si nuestra sesion recibe GPS en tierra para derivar la coordenada (EXP-013 sugiere que NO; la telemetria rica solo fluye volando) => de momento la coordenada se pasa por CLI.
- **Siguiente (seguro, sin vuelo): correr `flight.py` en DRY contra el Neo** (PC en su WiFi, dron asegurado). Exito = la ventana RX type-5 avanza con la secuencia COMPLETA (incluidos 0x03/0xf8, autoridad var-03, rafaga y heartbeat), confirmando aceptacion a nivel transporte de todas las piezas nuevas. Solo despues, y con las precauciones ya acordadas (exterior, supervisado, failsafe=Aterrizar), se plantea `--fly`.


### EXP-022 — LA CAUSA REAL DEL "NO ARMA": mandabamos solo el paso 1 de una maquina de estados de despegue de 4 pasos (2026-07-13)
> **[CORREGIDO EN EXP-024]** — FALSO. La "maquina de estados de despegue" (0x03/0xda 05->0a->07->08->0d) es **Detection**, no despegue. `0x03/0xda:05` = Detection.SetSwitch (aparece en sesiones SIN vuelo, periodico ~30s). El despegue real es FunctionControl `0x03/0x2a:01` AUTO_FLY, que nunca mandamos. Este EXP identifico bien el patron de bytes, pero le atribuyo mal el proposito.
- Estado: [OBSERVED, DECISIVO] — corrige EXP-020/021 y descarta la teoria del GPS/var-03 como bloqueo.
- Contexto: en hardware, `flight.py --fly` (var-02) hizo que el **modo Manual SI se ejecutara en el flight controller** (primer comando confirmado a nivel FC, no solo transporte) pero **el despegue NO armo**. Se probo 2 veces, mismo resultado.
- Refutacion de la teoria del GPS (correccion del asistente): el Neo **vuela en interior con vision system** (el usuario ha grabado su cuarto volando indoors) => el GPS NO es precondicion de armado. Pista falsa, descartada.
- **Hallazgo real (de `unwrap.py` sobre Octava/Quinta):** el despegue de la app NO es "repetir 0x03/0xda:05". Es una **maquina de estados**:
  1. `05 ffffffff` — INICIAR despegue (una vez).
  2. `0a 01` — confirmar (~0.4 s despues).
  3. `07 <fecha/hora> <len 0x13> <ID vuelo 19 dig>` — la **fecha/hora** es reproducible; el **ID de 19 digitos `2075123072524943360` es IDENTICO en Quinta y Octava** (2 sesiones/dias) => constante, hardcodeable.
  4. `08` — COMMIT (aqui arma de verdad; a veces x2).
  5. `0d <ts u32> <cola 12B>` — stream de control en vuelo continuo ~1 Hz que mantiene el vuelo.
  - Nuestro `flight.py` repetia SOLO el paso 1 a 15 Hz y jamas mandaba 0a01/07/08 ni el stream 0d. Le deciamos "iniciar" 30 veces y nunca "confirmar/commit". Por eso el FC obedecia el modo pero rechazaba el despegue: **secuencia de armado incompleta.**
- **Correccion de codigo (validada byte a byte):**
  - `neo_udp.py`: builders `arm_confirm_frame` (0a01), `arm_datetime_frame` (07, fecha actual + ID constante), `arm_commit_frame` (08), `flyctrl_stream_frame` (0d). `validate_arm.py`: **15/15 OK en Quinta Y Octava** (incl. `id_const=True`).
  - `flight.py`: el despegue ahora ejecuta `arm_sequence()` = 05 -> 0a01 -> 07 -> 08, y luego streamea el control 0x0d (1 Hz) + heartbeat 0x03/0xd7 + neutro en hover/aterrizaje. Se elimino el "hold" a 15 Hz del 05.
  - Freno de seguridad: como esta version SI puede armar, pide una **confirmacion tecleada ("VOLAR")** antes del commit; aborta si stdin no es interactivo.
- **Incognita restante:** el stream `0d` se replica estructuralmente (ts incremental + cola copiada de un frame real); no se conoce la semantica de todos sus campos. El armado/commit podria depender solo de 05->0a01->07->08; el `0d` sostiene el vuelo. Se sabra en la prueba.
- **Siguiente (EXTERIOR, area despejada, supervisado; lo teclea el usuario, no el asistente):** `flight.py --fly --armed-ok` -> confirmar "VOLAR" -> observar si arma/despega. var-02 primero; si no arma, añadir --lat/--lon (var-03). El asistente NO ejecuta el despegue real.


### EXP-023 — EL COMMIT VA ENVUELTO EN 0x51/0x01: mandabamos crudos los comandos que arman (2026-07-13)
> **[MATIZADO EN EXP-024]** — El hallazgo del envoltorio `0x51/0x01` es CORRECTO y sigue vigente: el despegue real (FunctionControl `0x03/0x2a`) tambien va envuelto ahi. Pero los frames que aqui se llamaban "de armado/commit" (0x03/0xda) eran Detection, no el despegue. El wrapper era necesario pero se aplicaba al comando equivocado.
- Estado: [OBSERVED, DECISIVO] — corrige EXP-019 ("el envoltorio no es candado") y completa EXP-022.
- Pista de hardware: `flight.py --fly` (ya con la maquina de estados 05->0a01->07->08, EXP-022) en EXTERIOR: **el modo cambia pero NO arma**, y la **ventana RX type-5 del dron queda congelada en el seed 0x7268** mientras nuestro seq corre a ~0x7790. El dron no consume nuestros comandos de armado.
- **Hallazgo (clasificacion BARE vs WRAP del uplink en Quinta y Octava):**
  - **BARE (crudos):** SOLO `0x03/0x20` (autoridad, var-02 y var-03) y `0x03/0xda:05` (iniciar).
  - **ENVUELTOS en `0x51/0x01`:** TODO lo que arma — `0x03/0xda` sub `0a`/`07`/`08`/`0d`, `0x03/0xf8` (params), `0x03/0xf9` (modo), `0x03/0x34`, `0x03/0x3c`, `0x0d/0x03`, `0x03/0xd7` (heartbeat).
  - Nuestro `flight.py` mandaba TODO crudo. El FC ignora el commit crudo (llega por transporte pero no por el canal de "transmision transparente" que el FC atiende) => modo si, armado no. EXP-019 concluyo mal porque solo miro el `05` (que si va crudo); los pasos de commit van envueltos.
- **Estructura del contenedor `0x51/0x01` (decodificada):** outer `snd=0x3b rcv=0xe9 attr=0x00 cmd 0x51/0x01`, dseq = contador del canal; `payload = <frame DUML interno completo> + cola(22B)`; `cola = 00 99d4ac02 <dseq:u32 LE> ffffffff 0182 00*7` (`99d4ac02` y `0182` fijos entre sesiones).
- **VALIDACION:** nuevo builder `neo_udp.wrap_5101`. `validate_arm.py` reconstruye **Quinta 4772/4776** y **Octava 2152/2156** frames envueltos byte a byte (los ~4 fallos por captura son frames con `0x55` anidado en su payload, irrelevantes). Total: **16/16 comprobaciones OK en ambas**.
- **Cambio de codigo:** `flight.py` ahora envuelve en `0x51/0x01` (con `_wrapped()` y contador `wdseq`) el modo, `0x03/0xf8`, la rafaga, la confirmacion/07/commit, el stream `0d` y el heartbeat `0x03/0xd7`; deja bare la autoridad y el `05`. Test offline: CRCs OK, envoltura correcta por comando.
- **Siguiente (EXTERIOR, supervisado; lo teclea el usuario):** reintentar `flight.py --fly --armed-ok`. Si ahora la ventana RX **avanza** durante el armado y el dron arma/despega => el envoltorio era la pieza que faltaba. Si sigue sin armar pese a avanzar la ventana, el sospechoso pasa a los lotes `0x03/0xf8` completos a rcv=0x17 y/o el stream `0x51/0x13`.


### EXP-024 — EL DESPEGUE REAL ES FunctionControl 0x03/0x2a AUTO_FLY, no 0x03/0xda (2026-07-13)
- Estado: [CONFIRMED NEO] — corrige EXP-019/021/022. Cross-check del codigo historico DJI P3 (ctomichael/fpv_live) contra Quinta/Octava + todas las capturas.
- Disparador: `flight.py` seguia sin despegar aun con la maquina de estados 0x03/0xda envuelta (EXP-023). El usuario aporto el mapa historico P3, donde `0x03/0xda`=`Detection` (sub 05=`SetSwitch`+uint32) y `0x03/0x2a`=`FunctionControl` (01=AUTO_FLY, 02=AUTO_LANDING, 07=START_MOTOR, 08=STOP_MOTOR, 22=PRECISION_TAKE_OFF).
- Herramienta: **`analysis/func_control_probe.py`** — escaneo DUML RECURSIVO (bare + envuelto + anidado, up + down, cualquier profundidad) buscando 0x03/0x2a y reconstruyendo el timeline del despegue.
- **PRUEBA CAUSAL (nuestras propias capturas):**
  - **`0x03/0x2a:01` AUTO_FLY (envuelto en 0x51/0x01, rcv=0x03) aparece SOLO en las 4 sesiones con vuelo real** — Quinta (t+21.4), Octava (t+19.2), Cuarta (t+40.0), Tercer (t+52.2) — y el dron responde **DN `0x03/0x2a`=00 (ack)**. `0x03/0x2a:02` AUTO_LANDING aparece en la fase de aterrizaje de cada una.
  - **AUSENTE** en las sesiones sin vuelo: Primera, Segunda, **Septima** (cambio de modos en tierra), Sexta (nuestra).
  - **`0x03/0xda:05` esta DECORRELACIONADO del despegue:** aparece en Septima (SIN vuelo) y a **intervalos fijos de ~30 s** (Quinta t+9.9/39.9/69.9/99.8) = housekeeping periodico de Detection. Su coincidencia temporal con el despegue era eso, coincidencia.
- **Validacion byte a byte del despegue real:** frame interno AUTO_FLY `550e04660203<dseq>40032a01<crc16>`; en Octava `550e04660203658840032a01df87`, envuelto en `0x51/0x01`. `validate_arm.py` reconstruye AUTO_FLY y AUTO_LANDING identicos en Quinta y Octava. Total: **18/18 comprobaciones OK en ambas** (+ wrapper 4772/4776 y 2152/2156).
- **Confirmacion del mapa P3 en el Neo** (cada ID cruzado contra el comportamiento medido): `0x20` SendGpsToFlyc (=EXP-020 exacto), `0x2a` FunctionControl, `0x34` GetPlaneName, `0x3c` GetFsAction, `0xd7` GetPushFlightRecord, `0xf8` GetParamsByHash, `0xda` Detection. El Neo reutiliza los command IDs de la generacion P3.
- **Cambios de codigo (todo validado, sin hardware):**
  - `neo_udp.py`: nuevo `funcctrl_frame(dseq, action)` con `AUTO_FLY=0x01`/`AUTO_LANDING=0x02`. Los builders de 0x03/0xda renombrados a `detection_*` (SetSwitch/0a/07/08/0d) y marcados housekeeping; `0x34`->`get_plane_name_frame`, `0x3c`->`get_fs_action_frame`, `0x0d/0x03`->`frame_0d03`.
  - `flight.py`: secuencia nueva **HELLO -> init -> modo Manual (envuelto) -> AUTO_FLY (envuelto) -> hover NEUTRO -> AUTO_LANDING (envuelto)**. Detection/params son ahora **opcionales** (`--detection-prep`), NO se asume precondicion. Ctrl+C = AUTO_LANDING. Se elimino la falsa "arm_sequence"/throttle-min.
  - Scripts legacy `arm_takeoff.py`/`init_takeoff.py`/`diag_takeoff.py` marcados **[DEPRECADO — EXP-024]**.
  - Entradas EXP-019/021/022 marcadas con su correccion; EXP-023 (envoltorio) matizado (sigue vigente).
- **Piezas eliminadas por falsa atribucion:** `0x03/0xda 05ffffffff` como "takeoff"; la "maquina de estados de armado" 05/0a/07/08 como despegue; el `0x0d` como "control de vuelo que mantiene el vuelo"; la idea de que var-03/coordenada o el GPS eran el bloqueo.
- **[INFERRED, sin probar]** AUTO_FLY llega ~10-30 s despues del prep de Detection en las 4 capturas => el prep/settle *podria* ser precondicion; no demostrado. Por eso `--detection-prep` existe pero esta OFF por defecto.
- **Siguiente (EXTERIOR, supervisado; lo teclea el usuario):** `flight.py --fly --armed-ok` -> VOLAR. Si AUTO_FLY arma => confirmado end-to-end. Si no, reintentar con `--detection-prep`. No se ejecuta hardware en este EXP.


### EXP-025 — EL ENGANCHE DE SESION: el handshake de suscripcion 0x51 es lo que hace que el FC procese nuestros comandos (2026-07-14)
- Estado: [OBSERVED, DECISIVO] — resuelve el bloqueo de fondo (EXP-017 en adelante): por que el dron aceptaba en transporte pero el flight controller ignoraba AUTO_FLY/modo/todo.
- Contexto: con transporte OK (EXP-018), envoltorio OK (EXP-023), keepalive OK (fix de sesion viva) y el comando de despegue correcto (EXP-024, `0x03/0x2a:01` AUTO_FLY), el `--fly` seguia sin armar y la ventana se quedaba plana. Se investigo en internet + se uso el dissector autoritativo **`tools/dji-firmware-tools`** (ya clonado): cruzados TODOS nuestros comandos contra el -> estaban bien formados (`0x2a` Function Control 1 byte, `0xda` Detection, `0x20` SendGpsToFlyc, `0x34/0x3c/0xd7/0xf8/0xf9/0x43`...). => el bloqueo NO era la estructura de comandos.
- El paper "Behind The Wings" + la doc del protocolo: en el WiFi de DJI **no hay muro de autenticacion de comando**; los paquetes bien formados se ejecutan. => el problema tenia que ser de ENGANCHE de sesion, no de cripto.
- Herramientas nuevas (seguras, sin motores): **`analysis/func_control_probe.py`** (scan DUML recursivo bare+wrapped+anidado, up+dn), **`diag_authority.py`** (¿el FC responde a GETs?), **`osd_reason.py`** (lee el OSD del FC y decodifica `flyc_state` + `start_fail_reason` segun el dissector; offsets: flyc_state@30 mask0x7F, controller_state u32@32, start_fail_reason@38 mask0x7F).
- **Hallazgo del handshake `0x51` (de las capturas):** el dron se "abre" (sirve OSD, responde GETs) a ~t+9, tras un intercambio en el canal `0x51`:
  - La app manda, envuelto en `0x51/0x01` (inner snd=0xee rcv=0xe9): `0x51/0x02` (config), `0x51/0x06` y `0x51/0x08` (con el **serial del dron**), y un stream continuo `0x51/0x13` (UUID `2020ee4d-...` + contador @off39). El serial se extrae EN VIVO del downlink `0x51/0x08`/`0x51/0x13` (snd=0xe9). NO se hardcodea (device info).
  - Nosotros nunca mandabamos `0x51/0x13`/06/08. => el dron nos aceptaba en transporte pero **nunca enganchaba**; solo recibiamos `0x51/0x01 + 0x51/0x13(DN) + 0x07/0x94` y el FC ignoraba todo.
- **RESULTADO EN HARDWARE (osd_reason.py con el handshake 0x51):** ✅✅✅ **el dron ENGANCHO.** Tras enviar `0x51/02+06+08` con serial en vivo + stream `0x51/13`:
  - Empezo a pushear telemetria RICA: **OSD General `0x03/0x43` (81 frames)**, actitud `0x23/*`, `0x03/0xd7` (562), video, etc.
  - **El FC RESPONDE a nuestros GET (`0x34/0x3c`): True** — primera confirmacion de que el flight controller procesa nuestros comandos a nivel aplicacion.
  - OSD decodificado: **estado `GPS_Atti`, gps_used=True, `start_fail_reason = 0x00 'None/Allow start'` (fail_happened=False)** => **el FC PERMITE arrancar motores; NO hay precondicion bloqueando el armado.**
- **Conclusion:** AUTO_FLY nunca ejecuto no por el comando ni por una precondicion (el FC dice "allow start"), sino porque la sesion **no estaba enganchada** (faltaba la suscripcion `0x51`). Con el enganche, el FC nos procesa y permite motores. Es la ultima pieza; no es cripto (UUID<->serial), coherente con EXP-020.
- **Conexion WiFi (gotcha que costo mucho tiempo):** el Neo NO emite su AP en un arranque limpio; solo lo levanta al conectar DJI Fly (telefono). Un solo cliente (telefono fuera). El gate `netsh wlan show networks` da falsos negativos (cache) -> se quito; lo fiable es **re-emitir `netsh wlan connect` cada ~2s hasta obtener IP** (wrapper `scratchpad/run_neo.ps1`).
- **Siguiente (gated, lo teclea el usuario):** integrar el handshake `0x51` en `flight.py` (extraer serial en vivo -> `0x51/02+06+08` -> stream `0x51/13`) antes del modo/AUTO_FLY. Secuencia: HELLO -> init -> **suscripcion 0x51** -> modo -> AUTO_FLY -> hover -> AUTO_LANDING. Con la sesion enganchada, AUTO_FLY llega a un FC que ya nos procesa y permite motores. Riesgo fisico real -> precauciones de seguridad (area despejada, piso normal/sensor IR, Ctrl+C=AUTO_LANDING, supervisado).
