# Guía ejecutable — E-OBS-3: captura pasiva del WiFi Neo↔DJI Fly

> **Objetivo:** determinar topología (IP/puertos), aislar el canal de mando del de vídeo, y **resolver el gate**: ¿el DUML del Neo viaja en claro o cifrado a capa de aplicación? Es observación 100 % pasiva: no se envía nada al dron, no se modifica nada.
>
> **Setup:** Android **rooteado** (el mismo que pilota el Neo en DJI Fly) + PC con Wireshark. El mando RC-N3 **no** se usa aquí (queremos el enlace WiFi teléfono↔dron; el RC va por O4).

---

## Parte 0 — Preparación del PC (Wireshark + dissector DUML)

1. Instala **Wireshark** en el PC.
2. Clona el dissector DUML de la comunidad:
   ```bash
   git clone https://github.com/o-gs/dji-firmware-tools
   ```
   Los dissectors están en `dji-firmware-tools/comm_dissector/wireshark/` (`dji-dumlv1-proto.lua` y los `*-general.lua`, `*-flyc.lua`, etc.).
3. Copia **todos** los `.lua` de esa carpeta a la carpeta de plugins de Wireshark:
   - Windows: `%APPDATA%\Wireshark\plugins\` (créala si no existe).
   - Reinicia Wireshark. En *Help → About → Plugins* deberían aparecer los `dji-dumlv1-*`.

> Nota: el dissector fue escrito para DUML sobre serie/USB. Sobre UDP quizá haya que hacer *Right-click → Decode As…* apuntando el puerto UDP del mando a `dji-dumlv1`. Si el payload UDP empieza por `0x55`, casi seguro es DUML directo.

## Parte 1 — Preparación del Android (PCAPdroid en modo root)

1. Instala **PCAPdroid** en el Android de laboratorio (Play Store, F-Droid o [releases de GitHub](https://github.com/emanuele-f/PCAPdroid)).
2. Instala **DJI Fly** en ese mismo Android y verifica que **vuela el Neo** (conexión *Connect via Mobile Device*).
3. En PCAPdroid:
   - *Settings → Capture method →* **Root capture** (usa el daemon `pcapd` sobre `wlan0`; captura UDP crudo que el modo VPN podría perder). Concede root cuando lo pida.
   - *Target app:* selecciona **DJI Fly** (`dji.go.v5`) para reducir ruido. (Si dudas, captura todo y filtras luego.)
   - *Dump mode:* **PCAP file** (guardar a archivo). Opcional: *PCAP-over-IP* para verlo en vivo en Wireshark.

## Parte 2 — Identificar la IP del dron (antes de capturar)

1. Enciende el Neo, conéctalo por WiFi al Android (DJI Fly).
2. En Android: *Ajustes → WiFi → (red del Neo) → Avanzado* y anota:
   - **IP del teléfono** (ej. `192.168.2.20`)
   - **Puerta de enlace / Gateway** = **IP del dron** (probable `192.168.2.1` o `192.168.1.1`)
3. Apunta ambas en el log. Serán tu filtro principal.

## Parte 3 — Captura con secuencia controlada

> ⚠️ **Seguridad:** haz la Parte 3B en un espacio privado, abierto y despejado, lejos de personas/animales, con un método de corte de potencia a mano. Si tu entorno lo permite sin volar (dron sujeto/asegurado) mejor, pero el mando virtual necesita que el dron esté activo para que DJI Fly emita comandos.

**3A — Idle en tierra (topología + gate de cifrado):**
1. Inicia la captura en PCAPdroid.
2. Con el Neo encendido y conectado, **sin despegar**, deja DJI Fly abierto en la pantalla de vuelo 30 s (verás el vídeo en vivo y telemetría en la UI).
3. Detén la captura. Esto ya basta para: ver IP/puertos, separar vídeo (flujo grande dron→teléfono) de telemetría, y **mirar si el DUML va en claro**.

**3B — Secuencia de sticks (aislar el canal de mando):**
1. Inicia una **nueva** captura. Arranca un cronómetro y **anota el segundo exacto** de cada acción (esto es clave para correlacionar después):
   ```
   t=0s    despegue (hover estable)
   t=10s   THROTTLE arriba 3s, luego neutro 3s
   t=16s   THROTTLE abajo 3s, neutro 3s
   t=22s   YAW izquierda 3s, neutro 3s
   t=28s   YAW derecha 3s, neutro 3s
   t=34s   PITCH adelante 3s, neutro 3s
   t=40s   PITCH atrás 3s, neutro 3s
   t=46s   ROLL izquierda 3s, neutro 3s
   t=52s   ROLL derecha 3s, neutro 3s
   t=58s   aterrizar
   ```
   Mueve **un solo eje a la vez**, con pausas neutras claras entre movimientos. Cuanto más limpia y separada la secuencia, más fácil aislar qué bytes cambian.
2. Detén la captura. Exporta el `.pcap` y pásalo al PC (o cópialo por USB).

## Parte 4 — Análisis en Wireshark

1. Abre el `.pcap`. Filtro base: `udp && ip.addr == <IP_DRON>`.
2. **Topología:** identifica los puertos UDP. Espera:
   - un flujo **grande y continuo dron→teléfono** = vídeo,
   - paquetes **pequeños y periódicos teléfono→dron** = candidatos a mando.
   Usa *Statistics → Conversations → UDP* para ver quién habla con quién y volúmenes.
3. **Gate de cifrado (lo más importante):** mira los bytes del payload de los paquetes teléfono→dron:
   - Si muchos **empiezan por `0x55`** con un campo de longitud plausible detrás → **DUML en claro** ✅ (vía de control viable). Aplica *Decode As → dji-dumlv1* al puerto.
   - Si el payload parece **ruido de alta entropía** sin patrón → probable **cifrado a capa app** (gate cerrado por esa vía; pasamos al APK).
   - Confirmación cruzada estilo tesis JKU: compara payloads del **mismo tamaño** en distintos momentos; si ves bytes que **incrementan de a uno** (contadores/seq) y campos estáticos → es texto binario plano, no cifrado.
4. **Correlación mando↔stick:** usa tus timestamps de la Parte 3B. Salta al `t` de "YAW izquierda" y observa qué bytes del paquete teléfono→dron cambian respecto al hover neutro. Repite por eje. El objetivo mínimo: **ver qué campo del paquete corresponde a cada eje**.

## Qué anotar en `EXPERIMENT_LOG.md`

- IP dron / IP teléfono / gateway.
- Puertos UDP y cuál es vídeo vs mando (con volúmenes).
- **Veredicto del gate:** DUML en claro / cifrado / no concluyente (+ captura de pantalla de bytes).
- Si en claro: cmd_set/cmd_id observados y qué byte(s) mueve cada eje.
- Ruta al `.pcap` archivado.

## Criterios

- **Éxito:** se aísla el flujo UDP de mando y se determina si el DUML está o no cifrado a nivel de aplicación.
- **Fracaso:** PCAPdroid (incluso en root) no ve el tráfico DJI Fly↔Neo, o no se distingue mando de vídeo.
- **Si falla o no concluye:** pasar a E-OBS-4 (captura externa en modo monitor + descifrado con la PSK del propio Neo — requiere adaptador WiFi 5 GHz). Si el DUML resulta cifrado → la vía de control se traslada a E-OBS-5 (análisis del APK con Frida en tu Android rooteado).

---

**Referencias:** dissector DUML `o-gs/dji-firmware-tools/comm_dissector`; PCAPdroid `emanuele-f/PCAPdroid`; metodología de captura+descifrado y análisis de entropía: tesis JKU/digidow (Christof 2021). Ver [`SOURCES.md`](SOURCES.md).
