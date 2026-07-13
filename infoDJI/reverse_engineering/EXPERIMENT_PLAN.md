# Plan de experimentos

> Los 5 primeros experimentos, **en orden**, todos **no destructivos** y sin flashing. Empiezan por observación pasiva y análisis de software (riesgo mínimo). Cada uno arroja información aunque falle. Los resultados se anotan en [`EXPERIMENT_LOG.md`](EXPERIMENT_LOG.md).
>
> **Prerrequisitos físicos:** el Neo del usuario + un cable **USB-C de datos** (no de solo carga) + teléfono Android (preferido; iOS limita mucho la captura). Para E-OBS-4, un adaptador WiFi con modo monitor que cubra 5 GHz. Antes de cualquier prueba con hélices: retirarlas o usar protectores, lejos de personas/animales, corte de potencia a mano.

---

## E-OBS-1 — Inventario físico por USB-C + línea base offline

**Objetivo:** conocer la superficie física del Neo sin tocar nada: versión exacta de firmware (¿`wa521`?), interfaces USB expuestas (¿solo almacenamiento masivo, o también un puerto serie/CDC-ACM candidato a DUML?) y telemetría SRT por-frame. Cero riesgo, cero flashing.

**Herramientas:** cable USB-C de datos · Administrador de dispositivos de Windows (o `lsusb`) · USBPcap/Wireshark (captura USB) · DJI Assistant 2 (solo lectura) · `jetervaz/dji-telemetry` o goprotelemetryextractor (parseo SRT).

**Pasos:**
1. Activar *Video Caption/Subtitles* en DJI Fly y grabar un clip corto del cuarto → genera `.SRT` junto al `.MP4`.
2. Apagar la app; conectar el **DRON** (no el mando) por USB-C al PC.
3. Enumerar interfaces en Administrador de dispositivos: anotar si aparece solo almacenamiento masivo o también un puerto COM/serie o dispositivo CDC-ACM.
4. Copiar MP4+SRT a `data/raw/` y parsear el SRT; anotar campos (GPS, altitud, ISO, frame-counter).
5. Abrir DJI Assistant 2 **solo** para leer la versión exacta de firmware y exportar logs (**no** actualizar ni revertir).

**Resultado esperado:** el Neo monta almacenamiento masivo con los vídeos; el SRT parsea con metadatos por-frame; Assistant 2 muestra una versión tipo `V01.00.0400` (`wa521`). Posible aparición de un puerto serie DUML.

**Criterio de éxito:** se obtiene (a) versión de firmware exacta, (b) lista de interfaces USB, (c) SRT parseado a JSON/CSV con timestamps por-frame.

**Criterio de fracaso:** el dron no monta como almacenamiento (cable de solo carga), o el SRT no se genera / no parsea.

**Qué aprendemos aunque falle:** si no hay puerto serie, la vía DUML **por USB al dron** queda descartada (quedaría USB al **mando**). Si el SRT no parsea, el contenedor de telemetría del Neo difiere del Neo 2 y habría que reversarlo o usar los logs `.txt`.

---

## E-OBS-2 — Vídeo en vivo → tu red → ROS, vía RTMP nativo (resuelve el antiguo E1)

**Objetivo:** conseguir vídeo en vivo del Neo en tu red **sin ninguna ingeniería inversa**, usando el push RTMP oficial. Cierra el Hito 1 (secundario) del proyecto.

**Herramientas:** NGINX con módulo RTMP o MediaMTX en el PC · DJI Fly (teléfono) · ffmpeg/ffprobe · Wireshark (opcional, para ver el flujo TCP 1935).

**Pasos:**
1. Levantar un servidor RTMP local (`rtmp://IP-PC:1935/live`) en el PC.
2. En DJI Fly: *Transmission → Live Streaming → RTMP*, pegar la URL con una stream-key.
3. Volar en hover corto; verificar que el PC recibe el stream.
4. Con `ffprobe` medir códec (H.264), resolución, fps y estimar latencia extremo a extremo.
5. Guardar unos segundos a disco para validar decodificación.

**Resultado esperado:** stream H.264 en vivo llega al servidor local; recompresión y latencia notables por salir re-encodeado del teléfono.

**Criterio de éxito:** el servidor RTMP recibe y decodifica el vídeo del Neo de forma estable durante >30 s.

**Criterio de fracaso:** DJI Fly no permite URL RTMP arbitraria, o el stream corta constantemente.

**Qué aprendemos aunque falle:** si RTMP falla, el vídeo en vivo se reduce a captura de pantalla del teléfono; el pipeline de SLAM se apoyaría en el flujo USB offline en vez de en vivo.

---

## E-OBS-3 — Observación pasiva del WiFi teléfono↔Neo durante control con joystick virtual

**Objetivo:** determinar la topología (IP/puertos), aislar el canal de mando del de vídeo, y **resolver el gate**: ¿el DUML del Neo viaja cifrado a capa app o en claro?

**Herramientas:** PCAPdroid (Android, VPN local sin root) · Wireshark + dissector `dji-dumlv1` (o-gs/dji-firmware-tools) · el propio teléfono.

**Pasos:**
1. Instalar PCAPdroid y arrancar captura dirigida a DJI Fly.
2. Conectar el Neo por WiFi (*Connect via Mobile Device*) y entrar en *Manual Control*.
3. Ejecutar una secuencia controlada: 10 s hover, luego cada eje de stick por separado 5 s (throttle, yaw, pitch, roll).
4. Exportar el PCAP y abrirlo en Wireshark; identificar IP del dron (probable `192.168.x.1`), rango DHCP, puertos UDP de vídeo vs mando.
5. Buscar el magic byte `0x55` y aplicar el dissector DUML; comparar tamaños/patrones de paquetes por acción de stick.

**Resultado esperado:** enlace UDP hacia el dron; un flujo grande dron→teléfono (vídeo) y paquetes pequeños periódicos teléfono→dron (mando). Si aparece `0x55` con campos coherentes → DUML en claro; si es alta entropía → cifrado app-layer.

**Criterio de éxito:** se aísla el flujo UDP de mando y se determina si el DUML está o no cifrado a nivel de aplicación.

**Criterio de fracaso:** PCAPdroid no captura el tráfico de DJI Fly (sockets crudos fuera de la VPN local) o no se distingue mando de vídeo.

**Qué aprendemos aunque falle:** pasar a captura externa (E-OBS-4). Si el DUML resulta cifrado a capa app, el control por sniffing WiFi queda `[BLOCKED]` y la vía pasa al análisis del APK (E-OBS-5).

---

## E-OBS-4 — Captura externa del WiFi + descifrado con la PSK del propio dron

**Objetivo:** obtener una traza limpia a nivel 802.11 independiente de las limitaciones de PCAPdroid, descifrándola con la PSK del propio Neo (que el usuario posee).

**Herramientas:** adaptador WiFi con modo monitor (2T2R, 2.4/5 GHz) · `airodump-ng` / `tcpdump` en Linux · PSK del AP del Neo · Wireshark + dissector `dji-dumlv1` · `create_ap` (opcional, MITM puente).

**Pasos:**
1. Poner el adaptador en modo monitor en el canal del AP del Neo.
2. Capturar el handshake WPA2 de 4 vías al asociarse el teléfono.
3. Grabar una sesión de vuelo con la misma secuencia controlada de sticks que en E-OBS-3.
4. En Wireshark, introducir la PSK del Neo para descifrar el tráfico 802.11.
5. Aplicar el dissector DUML y correlacionar paquetes con las acciones de stick; validar CRC-8/CRC-16.

**Resultado esperado:** tráfico descifrado equivalente al de E-OBS-3 pero completo a nivel enlace; confirmación cruzada de si el DUML está en claro.

**Criterio de éxito:** traza 802.11 descifrada con la PSK propia y paquetes de mando identificados/decodificados (o confirmados como cifrados).

**Criterio de fracaso:** el adaptador no captura el tráfico del dron (banda 5 GHz no soportada) o la PSK no descifra (esquema no-WPA2-PSK estándar).

**Qué aprendemos aunque falle:** si la PSK no descifra, el enlace del Neo usa un handshake distinto al Mavic Pro 1 documentado; habría que reversar el emparejamiento. Confirma que la vía de control se traslada al análisis del APK.

---

## E-OBS-5 — Análisis estático de DJI Fly (`dji.go.v5`)

**Objetivo:** mapear la estructura de protección SecNeo y localizar, **sin ejecutar**, los puntos de la cadena joystick→serialización, preparando el volcado dinámico posterior (Frida).

**Herramientas:** APK `dji.go.v5` (apkpure/apkcombo) · apktool · JADX/jadx-gui · Ghidra (para las `.so`) · jadx-native-libraries-plugin.

**Pasos:**
1. Descargar el APK y descomprimir; listar las `.so` (esperado: `libDexHelper.so` packer, `libwaes.so` whitebox).
2. Confirmar el wrapper `com.secneo` como punto de entrada y que las clases DJI están cifradas.
3. En JADX, inspeccionar lo poco visible en claro y localizar llamadas `System.load`/`native`.
4. Cargar `libDexHelper.so` en Ghidra para entender el flujo de descifrado RC4 de los dex (preparación del volcado con Frida).
5. Documentar strings/clave XOR si son recuperables y anotar candidatos de métodos JNI relacionados con control.

**Resultado esperado:** se confirma SecNeo y la necesidad de desempaquetado dinámico; se identifican las `.so` y la frontera Java→nativo, sin todavía el código de control en claro.

**Criterio de éxito:** mapa claro de la protección y plan concreto de volcado (qué hookear, qué dex esperar) para la fase Frida.

**Criterio de fracaso:** el APK descargado no corresponde al Neo (versión incompatible) o está tan ofuscado que no se identifica el punto de entrada nativo.

**Qué aprendemos aunque falle:** si el estático no da nada útil, se salta directo al volcado dinámico con Frida (replicando Synacktiv/Quarkslab), asumiendo dispositivo root y bypass anti-Frida como prerrequisito.

---

## Después de los 5 primeros

Según el resultado del **gate** (E-OBS-3/4):
- **DUML en claro** → mapear cmd_set/cmd_id de vuelo correlacionando sticks↔paquetes; construir un emisor con `pyduml`/`B3YOND`; primer intento de *un solo eje* con el dron asegurado y sin hélices.
- **DUML cifrado** → volcado dinámico del APK con Frida (dex2jar + JADX + Ghidra sobre `.so`) para recuperar la serialización del stick desde el código, independientemente del cifrado en el cable.

Solo mucho después: takeoff/land, control por ejes, y — si todo lo anterior funciona — position/XYZ/waypoints e integración con ROS 1 (`dji_neo_driver`).
