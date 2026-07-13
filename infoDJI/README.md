# infoDJI — Investigación técnica: DJI Neo como robot aéreo doméstico

Documentación de investigación para el proyecto de mapeo y navegación semántica de una casa de 3 pisos usando un **DJI Neo (original)** como plataforma inicial de captura.

## Objetivo del proyecto

Construir un sistema tipo "robot aéreo doméstico" capaz de:

1. Recorrer una casa de 3 pisos (inicialmente con vuelo manual).
2. Observar y memorizar visualmente el entorno con la cámara principal.
3. Construir un mapa 3D mediante SLAM/VIO.
4. Reconocer habitaciones, puertas, muebles, escaleras y objetos.
5. Crear waypoints semánticos (sala, cocina, oficina, recámaras, terraza, escaleras).
6. Localizar al dron dentro del mapa.
7. Visualizar todo en ROS 1 + RViz (fase de ingeniería/debug).
8. Mostrar el mismo world model en una web con Three.js / React Three Fiber.
9. (Futuro) Seleccionar un waypoint y ordenar al dron ir hacia él con planificación de rutas y evasión de obstáculos.

## ⚠️ Prioridad absoluta (cambiada 2026-07-10)

> **Conseguir control programático reproducible del DJI Neo original** desde software propio, vía ingeniería inversa (interoperabilidad, dron propio, entorno privado), e integrarlo después con ROS 1. Toda esta línea de trabajo vive en **[`reverse_engineering/`](reverse_engineering/README.md)** — empezar por su `README.md`, `ATTACK_SURFACE.md` y `EXPERIMENT_PLAN.md`.
>
> Regla: nunca afirmar que el Neo "es imposible de controlar". La conclusión correcta es `[NO CONFIRMED PATH]` (no hay vía pública demostrada aún; investigamos si puede descubrirse).

## Prioridad secundaria (antiguo hito 1)

> **vídeo del DJI Neo → procesamiento externo → ROS 1 → mapa/localización → visualización en RViz**
>
> Nota: la investigación confirmó que este pipeline de vídeo puede alimentarse **hoy y sin RE** vía RTMP nativo del Neo o el flujo USB offline (ver `reverse_engineering/NETWORK_RESEARCH.md`).

## Índice de documentos

| Documento | Contenido |
|---|---|
| [DJI_NEO_CAPABILITIES.md](DJI_NEO_CAPABILITIES.md) | Capacidades confirmadas del DJI Neo |
| [DJI_NEO_LIMITATIONS.md](DJI_NEO_LIMITATIONS.md) | Limitaciones conocidas (sin SDK, sin obstacle avoidance completo, sin API de control) |
| [DJI_NEO_SENSORS_AND_TELEMETRY.md](DJI_NEO_SENSORS_AND_TELEMETRY.md) | Sensores inferiores, infrarrojo, telemetría y qué es accesible |
| [DJI_NEO_VIDEO_AND_VISION.md](DJI_NEO_VIDEO_AND_VISION.md) | Vídeo, streaming y pipeline de visión artificial |
| [HOUSE_MAPPING_ARCHITECTURE.md](HOUSE_MAPPING_ARCHITECTURE.md) | Mapa 3D global de la casa de 3 pisos, frames, waypoints semánticos |
| [ROS_RVIZ_THREEJS_ARCHITECTURE.md](ROS_RVIZ_THREEJS_ARCHITECTURE.md) | ROS 1 (Noetic) como fuente de verdad; RViz y Three.js como consumidores |
| [AUTONOMOUS_NAVIGATION_CHALLENGES.md](AUTONOMOUS_NAVIGATION_CHALLENGES.md) | Retos de navegación autónoma y capa drone-control adapter |
| [SOURCES.md](SOURCES.md) | Fuentes oficiales y técnicas |
| [EXPERIMENTS_TODO.md](EXPERIMENTS_TODO.md) | Experimentos pendientes y criterios de validación |
| **[reverse_engineering/](reverse_engineering/README.md)** | **Ingeniería inversa del Neo para control programático (prioridad absoluta): matriz de rutas, plan de experimentos, DUML, firmware, red, hardware, comunidad** |

## Convención de clasificación de información

Toda afirmación técnica en estos documentos se etiqueta con uno de estos niveles:

- ✅ **Confirmado oficialmente** — documentado por DJI o por la documentación oficial de la tecnología correspondiente.
- 🔧 **Técnicamente inferido** — se deduce razonablemente del funcionamiento del producto, pero DJI no lo documenta como API/capacidad pública.
- 🧪 **Experimental** — requiere validación práctica antes de asumirlo en la arquitectura.
- ❌ **No disponible** — no existe vía oficial conocida; no debe asumirse en el diseño.

**Regla de oro del proyecto:** no inventar capacidades que DJI no documente, y no acoplar el sistema al Neo — el Neo es la plataforma inicial de captura, no necesariamente la plataforma final de navegación.
