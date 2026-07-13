# Investigación de DUML / protocolo DJI

> **DUML** (a.k.a. "MB protocol") es el framing binario único que DJI reutiliza en prácticamente toda su flota. La wiki de RE de la comunidad lo dice literal: los paquetes están *"unified across all products"*. Bueno para nosotros: el **framing es agnóstico de producto**, así que el trabajo previo sobre Mavic/Spark/Mini/Avata transfiere al Neo a nivel de framing y semántica de comandos. Malo: la **capa de autenticación/cifrado de sesión** de esta generación y la **tabla concreta de cmd_id de vuelo del Neo** siguen sin resolverse públicamente.

## Estructura del paquete (DUML v1)

`[CONFIRMED]` por 4 fuentes primarias independientes (dissectors de dji-firmware-tools, tesis Christof 2021, `samuelsadok/dji_protocol`, `strazzere/duml-packet`):

```
0x55            SOF (magic byte)
len (13 bits) + version (3 bits)     longitud + versión de protocolo (v común 0x04)
CRC-8           sobre los 3 primeros bytes de header (poly 0x31, init 0xEE, reflejado)
sender ID
receiver ID
seq (16 bits, little-endian)         número de secuencia
attr byte                            bits IS_ACK / NEED_ACK
cmd_set                              conjunto de comandos
cmd_id                               comando
payload (variable)
CRC-16 (little-endian)               sobre el paquete completo
```

> Verificar `init 0xEE` / seeds directamente en el código: `DUML.rb` de DUMLrub y `comm_mkdupc.py` reportan header CRC-8 seed `0x77` y frame CRC-16 seed `0x3692` en la ruta serial — anotar cuál aplica al capturar y validar contra frames reales del Neo.

## Command sets

`[CONFIRMED]` ~17 command sets conocidos, indexados por `cmd_set`. Cada uno tiene su propio dissector Lua (documentación viva de cmd_id y payloads):
- `0x00` **General** — Ping, Version Inquiry, Enter Loader, Update Transmit, Reboot Chip, **Get Device State** (comandos de **lectura seguros**).
- `0x03` **Flight Controller** — FlyC Status/Params, Origin GPS Set/Get, Nofly Zone Set, Battery Status. *(Aquí vivirían los comandos tipo virtual-stick — zona de alto riesgo.)*
- Camera, Gimbal, WiFi, Battery, etc.

## `[OBSERVED, 2026-07-13]` Encapsulado sobre el UDP fiable de DJI (no DUML-serie puro)

Por WiFi el Neo no habla DUML-serie plano: cada frame MB (`0x55…`) viaja como **payload** de un paquete del protocolo UDP fiable de `samuelsadok/dji_protocol` (ver [`NETWORK_RESEARCH.md`](NETWORK_RESEARCH.md)). Los comandos app→dron van en paquetes **type-5**, con el frame DUML a partir del offset `0x14`. **Implicación práctica (EXP-018):** un frame DUML con CRC-8/CRC-16 correctos **no basta** — si la cabecera UDP fiable que lo envuelve tiene el XOR (`0x07`), el seq (`0x04-05`, paso +8 desde el seed) o las ventanas mal, el dron lo descarta **antes** de llegar a la capa DUML. Esto explica por qué nuestros comandos con DUML válido eran ignorados. Builder correcto y validado: `tools/neo_control/neo_udp.py`.

## Variantes de transporte

`[CONFIRMED]` al menos dos: **"V1"** (frame para PC↔dron por USB) y un protocolo interno **"Logic"** entre módulos del dron (UART/CAN, con SPI proxeado por un módulo DUML vecino). Para el Neo, el **USB-C es la superficie DUML más accesible** (V1). Además, la investigación de Nozomi sobre Mavic 3 mostró que la capa **WiFi/QuickTransfer** también transporta DUML → segunda superficie candidata en el Neo.

## Transferibilidad al Neo — y lo que falta

- **`[CONFIRMED]`** El framing y el esquema de direccionamiento de módulos son agnósticos de producto por diseño de DJI → el Neo casi con seguridad habla DUML en su USB-C y buses internos, y la semántica de comandos de otros modelos O4 (Mini 4 Pro, Avata 2, Mavic 3) es el punto de partida más cercano.
- **`[INFERRED]`** Drones nuevos añaden cifrado/firma y autenticación de comandos que los DUML antiguos en claro no tenían; exploits de root como **DUMLRacer** fueron parcheados (solo hasta firmware `v01.04.0200`). → El **framing** transfiere, pero un **exploit de control** puede no hacerlo: el bloqueador probable es la capa auth/crypto, no el formato del paquete.
- **`[OBSERVED]`** El Neo **no aparece** en la lista de modelos soportados de ninguna herramienta pública (dji-firmware-tools enumera WM/GL; drone-hacks tope en Air 2S/FPV). `wa521` no está en ninguna tabla.
- **`[UNKNOWN]`** No hay captura, mapa de cmd_set/cmd_id, ni handshake de sesión (pairing/auth) específicos del Neo en ningún idioma. **Es exactamente el hueco que llenaría un experimento propio.**

## Herramientas maduras y reutilizables

`pyduml` (Python, pyserial, autodetección + RNDIS) · `DUMLrub` (Ruby) · `comm_serialtalk.py`/DUML Builder (dji-firmware-tools) · `strazzere/duml-packet` · `D3VL/B3YOND` (DUML por WebSerial/WebUSB, el más moderno) · dissectors Lua para Wireshark. Ninguno cubre el Neo, pero sirven de andamiaje.

## Camino seguro de sondeo (antes de tocar vuelo)

Con `pyduml`/`comm_serialtalk.py` por USB, enviar **solo** comandos General (`0x00`) de **lectura** (Ping, Version Inquiry, Get Device State) y registrar qué módulos hacen ACK → confirma que el Neo habla DUML y enumera sus módulos, **antes** de acercarse a `cmd_set` de flight-control.

**Fuentes clave:** `o-gs/dji-firmware-tools` (comm_dissector, wiki); tesis Christof 2021; `samuelsadok/dji_protocol`; `strazzere/duml-packet`; `MAVProxyUser/DUMLrub`; `hdnes/pyduml`; Nozomi Mavic 3 research; `CunningLogic/DUMLRacer`. Lista completa en [`SOURCES.md`](SOURCES.md).
