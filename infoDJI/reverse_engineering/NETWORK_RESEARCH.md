# Investigación de red — enlace Neo ↔ DJI Fly

> Foco: el transporte por donde viajan mando, telemetría y vídeo cuando el Neo se pilota **solo con teléfono** (sin RC/gafas). Es la superficie de control más accesible.

## Topología (qué esperar)

- **`[CONFIRMED]`** El Neo se conecta al teléfono directamente por WiFi con *Connect via Mobile Device* (sin RC). El **dron actúa como Access Point** y el teléfono se asocia como cliente. Alcance efectivo ~50 m. WiFi 802.11a/b/g/n/ac + Bluetooth 5.1. → *Fuentes: soporte DJI 01700011389; oscarliang.com.*
- **`[CONFIRMED]` (en Mavic Pro 1, `[INFERRED]` para Neo)** Arquitectura estándar de la familia WiFi de DJI: el dron es el AP con IP `192.168.2.1`, el operador recibe IP por DHCP, y **todo** el tráfico app↔dron (mando + telemetría + vídeo) viaja sobre **UDP**. Cifrado de transporte: **WPA2-PSK en modo CCMP** (AES-CTR + CBC-MAC), handshake 802.11i de 4 vías. → *Tesis JKU/digidow (Christof 2021).*
- **`[UNKNOWN]`** Las IP/puertos exactos del Neo (¿`192.168.2.1`? ¿`.1.1`?) y el puerto/formato del vídeo (RTP crudo vs contenedor DJI H.264/H.265). Hay que capturarlos.

## `[OBSERVED, 2026-07-13]` El transporte es el protocolo UDP fiable de `samuelsadok/dji_protocol`

Reanálisis de capturas propias (EXP-018) confirma **byte a byte** que el "wrapper de sesión" del Neo **es** el protocolo UDP propietario documentado en `samuelsadok/dji_protocol` (`udp_protocol.md`), el mismo del Mavic Pro 1. Cabecera común de 8 bytes en todo paquete UDP 9003:

| offset | campo |
|---|---|
| `0x00-01` | longitud (bits 14:0), bit15 = 1 |
| `0x02-03` | session id |
| `0x04-05` | **número de secuencia** (≠0 solo en tipos 0x02/0x03/0x05) |
| `0x06` | **tipo de paquete** (0x00 hello … 0x06) |
| `0x07` | **XOR de los bytes 0..6** (checksum de cabecera) |

Tipos: `0x00` handshake · `0x01` telemetría (dron→app, 10 Hz) · `0x02` vídeo H.264 (dron→app, 30 Hz) · `0x04`/`0x06` ACK (app→dron) · `0x05` **comandos** (app→dron). Los streams `0x02`/`0x03`/`0x05` son **fiables**: llevan seq (paso **+8**, sembrado por `seed` en `0x08-09` del hello) y ventanas de envío/recepción para retransmisión. El dron reporta su ventana RX type-5 en `0x18-0x1b` de sus type-1. **`[CONFIRMED empíricamente]`** validación XOR 0 fallos en 89.000+ paquetes; reconstrucción 8/8 de comandos type-5 reales. Detalle en [`EXPERIMENT_LOG.md`](EXPERIMENT_LOG.md) EXP-018.

## El gate crítico: ¿DUML cifrado a capa app?

- **`[CONFIRMED]` (Mavic Pro 1, 2016)** Una vez descifrado el WiFi, el payload DUML viajaba **sin cifrado adicional**: reversable byte a byte. La tesis analizó >20 000 paquetes UDP/min y descartó cifrado de capa app (contadores que incrementan de a uno, campos estáticos, patrones repetidos).
- **`[UNKNOWN]` (Neo, 2024)** Si el Neo añadió cifrado de capa app sobre DUML, ese es el bloqueador real. **No existe captura pública del Neo que lo resuelva.** Es lo que responden E-OBS-3/E-OBS-4.
- **`[OBSERVED]`** El vídeo en drones DJI WiFi antiguos se vio como stream UDP dedicado (p.ej. Phantom UDP:9000 desde `192.168.1.10`); vídeo y mando suelen compartir el enlace UDP pero pueden ir en puertos distintos. El esquema de IP varía por modelo (`192.168.1.x` vs `.2.x`).

## Métodos de captura (de menor a mayor esfuerzo)

1. **`[EXPERIMENTAL]` PCAPdroid** (Android, VPN local, **sin root**): el teléfono es un extremo del enlace, así que ve el tráfico DJI Fly↔Neo. Limitaciones: captura a nivel IP dentro del teléfono, no descifra capa app si existiera; algunos sockets crudos pueden escaparse de la VPN local. → E-OBS-3.
2. **`[CONFIRMED]` como método (en MP1)** Captura externa en **modo monitor** (adaptador 2T2R que cubra 5 GHz) + descifrado con la **PSK del propio dron** (que el usuario posee) en Wireshark. → E-OBS-4.
3. **MITM con `create_ap`** (Linux): el PC hace de AP puente entre teléfono y dron, viendo el tráfico ya descifrado (método de la tesis JKU).

Filtros útiles: `udp host 192.168.x.1`, `!dns && !mdns && !icmp`, `data.len==N` para aislar mando (paquetes pequeños periódicos teléfono→dron) de vídeo (flujo grande dron→teléfono).

## Vídeo en vivo sin RE (ruta oficial)

- **`[CONFIRMED]`** DJI Fly soporta push **RTMP** para el Neo: *Transmission → Live Streaming → RTMP*, URL `rtmp://servidor:1935/app/streamkey` hacia un NGINX-RTMP/MediaMTX local. El push **sale del teléfono** (re-encodeado), no del dron: latencia + recompresión, y requiere la app abierta. Da solo vídeo, ni mando ni pose. → E-OBS-2.

## Nota de contraste

- **`[CONFIRMED]`** El Tello (Ryze/DJI) sí expone SDK UDP abierto (`192.168.10.1:8889` mando, `:8890` estado, `:11111` vídeo), pero el Neo **no** usa ese SDK. Útil solo como referencia de a qué "huele" un canal de mando UDP al capturar.

**Fuentes clave:** tesis JKU/digidow (`digidow.eu/.../Christof_2021...pdf`, espejo `epub.jku.at/.../6966648`); `o-gs/dji-firmware-tools` comm_dissector; `emanuele-f/PCAPdroid`; `Toemsel/dji-wifi-tools`; guía RTMP Bliksund; hilo MavicPilots "low-level wifi protocol RE". Lista completa en [`SOURCES.md`](SOURCES.md).
