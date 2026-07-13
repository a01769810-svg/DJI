# DJI Neo — Limitaciones conocidas

Estas limitaciones definen el perímetro real del proyecto. Ninguna decisión de arquitectura debe contradecirlas sin evidencia experimental nueva.

## 1. ❌ Sin SDK oficial compatible (limitación principal)

El DJI Neo original **no aparece como aeronave soportada por DJI Mobile SDK V5** (fuente: [introducción oficial al MSDK](https://developer.dji.com/doc/mobile-sdk-tutorial/en/basic-introduction/msdk-introduction.html)).

Por tanto, **no existe actualmente una API oficial documentada** para obtener desde una app propia:

- GPS del dron
- posición XYZ
- altitud
- velocidad
- yaw / pitch / roll
- batería
- telemetría completa
- datos crudos del sensor infrarrojo
- imagen cruda de la cámara inferior
- comandos programáticos tipo **Virtual Stick**
- navegación autónoma por waypoints personalizados

**Ésta es la principal limitación del proyecto.**

## 2. ❌ Sin control programático

No hay vía oficial conocida para enviar al Neo órdenes como:

```text
avanza 50 cm
gira 15 grados
sube 20 cm
ve a XYZ
sigue esta trayectoria
```

Consecuencia de diseño: aunque el sistema pueda producir mapas, localización, waypoints y rutas planificadas, la **ejecución** de esas rutas sobre el Neo no es posible hoy por medios oficiales. La capa de control debe diseñarse como un adaptador intercambiable (ver [AUTONOMOUS_NAVIGATION_CHALLENGES.md](AUTONOMOUS_NAVIGATION_CHALLENGES.md)).

## 3. ❌ Sin evasión de obstáculos completa

El Neo **no dispone de un sistema convencional multidireccional de obstacle avoidance**. Sus sensores inferiores están orientados a posicionamiento y aterrizaje, no a detectar paredes, sillas, personas, puertas ni obstáculos laterales o frontales.

Consecuencias:

- **No asumir** que el Neo evitará obstáculos por sí mismo en interiores.
- Toda evasión de obstáculos para una futura navegación autónoma tendría que venir de **fuera** del dron: cámara RGB + SLAM + estimación de profundidad + detección de objetos + mapa 3D + planificación de trayectorias — y posiblemente sensores adicionales o una plataforma aérea más abierta.
- En interiores estrechos (escaleras, pasillos), el vuelo manual con el Neo ya es delicado; la navegación autónoma segura con solo su hardware actual es hoy **inviable**.

## 4. ❌ Sin acceso a sensores crudos

No hay documentación pública oficial para obtener frames de la cámara inferior, distancias del infrarrojo, lecturas individuales de sensores ni point clouds internos. Detalle en [DJI_NEO_SENSORS_AND_TELEMETRY.md](DJI_NEO_SENSORS_AND_TELEMETRY.md).

**Principio clave:** que el dron use internamente un sensor **no** significa que exista una API pública para acceder a sus valores.

## 5. 🧪 Telemetría en vivo: solo por vías no oficiales

DJI Fly muestra estados del dron, así que la comunicación interna existe (🔧 inferido). Extraerla requeriría reverse engineering (tráfico Neo↔Fly, logs, protocolos) — territorio experimental, sin garantías, y potencialmente frágil frente a actualizaciones de firmware. **No apoyar la arquitectura sobre esto** hasta demostrarlo (ver [EXPERIMENTS_TODO.md](EXPERIMENTS_TODO.md)).

## 6. Limitaciones prácticas adicionales para interiores (🔧 inferidas del tipo de producto)

- Cámara **monocular**: sin profundidad métrica directa; el SLAM monocular tiene ambigüedad de escala.
- Autonomía de batería limitada (vuelos cortos → mapeo por sesiones).
- Corrientes de aire propias (prop wash) cerca de paredes y techos en espacios estrechos.
- Ruido y seguridad al volar cerca de personas dentro de casa.

## 7. ❌ Control por WiFi con app/web propia — investigado y descartado

> **Investigación multilingüe (inglés, español, chino, japonés, alemán, sueco, francés, hindi), julio 2026.** 100 agentes, 17 fuentes primarias/foros, 24 de 25 afirmaciones confirmadas por verificación adversarial 3-0. **Conclusión: no existe ninguna vía documentada ni confirmada para controlar programáticamente el Neo por WiFi (ni por ningún otro canal).** Esta sección cierra la pregunta "¿podemos usar el WiFi del Neo para controlarlo nosotros?" — ya está investigada, no es un pendiente.

### 7.1 ❌ El WiFi del Neo solo expone control manual

El Neo crea su **propia red WiFi peer-to-peer** y se conecta directamente al smartphone vía DJI Fly, sin router externo. Pero el único control por ese canal son los **joysticks virtuales táctiles** de la app (alcance efectivo ~50 m). No hay API, no hay vector de red controlable por código propio.

- ✅ Confirmado (soporte oficial DJI): *"You can control DJI Neo using the virtual joysticks in the app"* — [DJI Support: Flip/Neo Series Mobile App Control](https://support.dji.com/help/content?customId=01700011389).

### 7.2 ❌ DJI confirmó oficialmente que no habrá SDK para el Neo

- ❌ Respuesta oficial del equipo de soporte SDK de DJI (issue #725, marzo 2026): *"the MSDK does not support the Neo series models such as the Neo 1 and Neo 2, and there are currently no relevant support plans"* — [Mobile-SDK-Android-V5 #725](https://github.com/dji-sdk/Mobile-SDK-Android-V5/issues/725).
- ❌ Foristas del Neo: *"Lacking an SDK, programmatic control is going to be difficult to impossible... the chances of DJI expending the resources for an SDK for this drone are very very scant"* — [NeoPilots Forum](https://neopilots.com/threads/djicontrolserver-and-mobile-sdk-support.1347/).
- 🔧 Refuerzo contextual: DJI **cerró su departamento STEAM/EDU** y descontinuó las líneas Tello/RoboMaster (dic-2023/ene-2024), por lo que un "SDK sencillo tipo Tello" para el Neo es muy improbable.

### 7.3 El contraste con el DJI Tello (por qué el Tello sí y el Neo no)

Esta es la lección clave de la investigación:

- ✅ **El DJI/Ryze Tello SÍ tiene control WiFi programático oficial**: conexión a su AP (`192.168.10.1`), **comandos de texto por UDP al puerto 8889** (`takeoff`, `forward 50`, `cw 90`…), estado en 8890, vídeo en 11111, desde Python (`DJITelloPy`) o Scratch — [Tello SDK 2.0 User Guide](https://dl-cdn.ryzerobotics.com/downloads/Tello/Tello%20SDK%202.0%20User%20Guide.pdf).
- **Implicación**: el control-WiFi *es técnicamente posible* en hardware DJI/Ryze, **pero solo cuando el fabricante lo habilita explícitamente** (el Tello se diseñó como producto educativo con ese SDK abierto a propósito). El Neo **no expone nada equivalente** — ningún esquema de puertos ni protocolo de control publicado.
- ➡️ **No se puede portar el enfoque Tello al Neo.** Son firmwares y filosofías de producto distintas.

### 7.4 🔧 El protocolo interno de DJI (DUML) no rescata el caso del Neo

- 🔧 DJI usa internamente el protocolo **DUML** ("MB protocol") en todos sus productos y canales; su estructura de paquete es conocida por RE (byte mágico `0x55`, cmd_set, cmd_id, CRC) — [tesis de máster, Christof 2021](https://www.digidow.eu/publications/2021-christof-masterthesis/Christof_2021_MasterThesis_DJIProtocolReverseEngineering.pdf), [dji-firmware-tools](https://github.com/o-gs/dji-firmware-tools).
- ❌ **Pero nadie lo ha aplicado al Neo.** Los proyectos de RE relevantes ([dji_protocol](https://github.com/samuelsadok/dji_protocol), [dji_rev](https://github.com/fvantienen/dji_rev), [dji-firmware-tools](https://github.com/o-gs/dji-firmware-tools)) cubren **solo modelos viejos** (Mavic Pro ~2017, Phantom 3/4, Spark, Mini 2). Ni el Neo ni el Tello aparecen en ninguno.
- 🔧 `dji_rev` es una herramienta de **firmware** (extraer/descifrar), **no de control en vivo**: aunque se extrajera el firmware del Neo, eso no da un canal de control.
- 🔧 La capa de transporte WiFi va **cifrada (WPA2-PSK/CCMP)**. Interceptar o inyectar tráfico requeriría la clave PSK **más** la lógica DUML específica del Neo — que nadie ha mapeado públicamente.

➡️ La ruta "sniffear DJI Fly con Wireshark e inyectar comandos DUML" es, para el Neo, **territorio no explorado por nadie públicamente** — no un camino trazado que se pueda seguir.

### 7.5 🧪 Única capacidad de red aprovechable: RTMP de vídeo (de salida)

- 🧪/✅ El Neo soporta **streaming RTMP vía DJI Fly** (menú Transmission → Live Streaming Platforms): el **teléfono** (no el dron) hace push de vídeo a un servidor `rtmp://servidor:1935/app/clave` — confirmado por guías dedicadas ([Bliksund](https://bliksund.com/blog-and-news/how-to-set-up-rtmp-streaming-on-the-dji-fly-app-for-the-dji-neo-drone-fpv-drone-guide), [AirHub](https://www.airhub.app/resources/news/live-streaming-dji-avata-2-fpv-rtmp-airhub)); la [página oficial de DJI](https://support.dji.com/help/content?customId=en-us03400006727) confirma RTMP en DJI Fly V1.4.12+ pero sin nombrar al Neo explícitamente.
- ❌ RTMP es **unidireccional por diseño**: transporta vídeo de salida, **no control ni telemetría de retorno**. No avanza el objetivo de control/automatización — solo sirve como *fuente de vídeo* para el hito 1.
- Limitación práctica: bitrate ~1–2 Mbps (iOS) / 3–5 Mbps (Android). **Pregunta abierta**: si la latencia/calidad bastan para SLAM/VIO en tiempo real (el push sale del teléfono, no del dron). Experimentable dentro del proyecto (ver [EXPERIMENTS_TODO.md](EXPERIMENTS_TODO.md)).

### 7.6 Preguntas que quedaron abiertas

- ¿Habla el Neo DUML por su enlace al teléfono, o usa OcuSync/SDR propietario que impide el ataque WiFi-UDP estilo Mavic Pro? Sin respuesta pública.
- ¿Existe algún proyecto de RE en comunidades no anglófonas (52pojie, bilibili, foro DJI CN, RCGroups) con capturas del Neo? La búsqueda en 8 idiomas **no encontró ninguno**.

## Resumen: qué implica todo esto

| Objetivo del proyecto | ¿Bloqueado por el Neo? |
|---|---|
| Capturar vídeo de la casa | No — viable (validar vía de streaming) |
| SLAM / mapa 3D / localización | No — se hace externamente con el vídeo |
| Reconocimiento semántico y waypoints | No — externo |
| Visualización RViz / Three.js | No — externo |
| Telemetría en vivo del dron | Sí — solo experimental/no oficial |
| Control por WiFi con app/web propia | **Sí — bloqueado** (investigado jul-2026; DJI descartó SDK, ver §7) |
| Streaming RTMP de vídeo vía DJI Fly | No — viable como fuente de vídeo (unidireccional, sin control; ver §7.5) |
| Navegación autónoma real con el Neo | **Sí — bloqueado hoy** (sin API de control ni obstacle avoidance) |
