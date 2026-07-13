# DJI Neo — Robot aéreo doméstico

Este archivo se carga automáticamente al inicio de cada sesión. Contiene el estado del proyecto y las reglas de trabajo.

## Objetivo

Usar un **DJI Neo original** para mapear una casa de 3 pisos: vídeo → SLAM/VIO → mapa 3D global → waypoints semánticos (sala, cocina, oficina, recámaras, terraza, escaleras) → visualización en ROS 1 + RViz, y más adelante en una web con Three.js / React Three Fiber.

**⚠️ PRIORIDAD ABSOLUTA (cambiada 2026-07-10):** el objetivo principal ahora es **conseguir control programático reproducible del DJI Neo original** desde software propio, vía ingeniería inversa (interoperabilidad, dron propio, entorno privado), e integrarlo después con ROS 1. El pipeline de vídeo→SLAM→RViz pasa a ser **secundario**. Investigación en **[`infoDJI/reverse_engineering/`](infoDJI/reverse_engineering/README.md)**.

**Regla fundamental:** NUNCA afirmar que el Neo "es imposible de controlar". La conclusión correcta es `[NO CONFIRMED PATH]`: no existe hoy una vía pública, documentada y demostrada; el objetivo es investigar experimentalmente si puede descubrirse una. No abandonar una línea solo porque no haya documentación oficial. Límites: solo hardware propio, entorno privado; NO atacar infraestructura DJI, NO jamming, NO drones ajenos, NO desactivar geofencing. NO flashing ni cambios irreversibles sin parar y avisar antes.

**Hito 1 (secundario):** demostrar `vídeo del Neo → procesamiento externo → ROS 1 → mapa/localización → RViz`.

La investigación completa está en **[`infoDJI/`](infoDJI/README.md)** — leerla antes de proponer arquitectura.

## Reglas de trabajo (acordadas con el usuario)

1. **No inventar capacidades que DJI no documente.** Toda afirmación técnica se etiqueta:
   - ✅ confirmado oficialmente · 🔧 técnicamente inferido · 🧪 experimental · ❌ no disponible
2. **No acoplar el proyecto al Neo.** El Neo es un *sensor volador* (fuente de vídeo), no el ejecutor de la navegación. La capa de control (`drone-control adapter`) debe ser modular e intercambiable (Neo / PX4 / simulador).
3. **Separación estricta de capas:** A) percepción y mapeo · B) localización · C) world model semántico · D) planificación de rutas · E) adaptador de control del dron.
4. **ROS 1 es la fuente de verdad.** RViz y Three.js son consumidores paralelos del mismo world model. Nunca `RViz → exportar → Three.js`.
5. El usuario escribe en español; responder en español.

## Decisión: ROS 1 (Noetic), no ROS 2

El usuario trabaja con **ROS 1**. Toda la documentación del proyecto asume Noetic. No proponer ROS 2, `rclpy`/`rclcpp`, `colcon` ni `ros2 launch`.

- **Distro obligada:** ROS Noetic sobre **Ubuntu 20.04 (Focal)** — es la única combinación soportada. No 22.04 ni 24.04.
- Herramientas: `catkin`, `roslaunch`, `rosrun`, `rosbag`, `rqt_image_view`, `rviz` (no `rviz2`).
- Noetic pinea **Python 3.8**. Los nodos ROS usan ese intérprete; el trabajo de ML pesado (YOLO en E5) va en un proceso/venv aparte que se comunica por topics, no dentro del nodo.

**Ventaja real de esta elección:** ORB-SLAM3, `octomap_server`, `rosbridge_suite`, `roslibjs` y `ros3djs` son todos nativos de ROS 1 — es la ruta con menos fricción para el hito 1, no un downgrade.

**Coste asumido (⚠️ conocido, aceptado):** Noetic llegó a *end of life* en **mayo de 2025** y Ubuntu 20.04 salió de soporte estándar en **abril de 2025**. No habrá parches oficiales. Es aceptable para un proyecto local de investigación; no lo sería para algo expuesto a red.

## Restricciones duras del DJI Neo (no negociables)

- ❌ **Sin SDK oficial** — el Neo no está soportado por DJI Mobile SDK V5.
- ❌ **Sin API de control programático** (no hay "ve a XYZ", "avanza 50 cm", Virtual Stick, waypoints propios).
- ❌ **Sin telemetría en vivo** oficial (GPS, pose, altitud, actitud, batería).
- ❌ **Sin acceso a sensores crudos** (cámara inferior, infrarrojo).
- ❌ **Sin obstacle avoidance multidireccional** — no asumir que evitará paredes ni muebles.

Consecuencia: la pose del dron **debe estimarse 100 % por visión externa**. La navegación autónoma real con el Neo está bloqueada hoy; se demostrará en simulación (PX4 SITL / Gazebo) sobre el mapa real.

Detalle en [`infoDJI/DJI_NEO_LIMITATIONS.md`](infoDJI/DJI_NEO_LIMITATIONS.md).

## Cómo se obtiene el vídeo

- ✅ **Offline (la vía del hito 1):** volar manualmente con DJI Fly, el Neo graba en su memoria interna (~22 GB, sin microSD). Aterrizar, conectar **el dron** (no el mando) por USB-C al PC, copiar archivos a `data/raw/`. **No requiere app abierta ni streaming.**
- 🧪 **En vivo (más adelante):** obligatoriamente pasa por DJI Fly (teléfono o pantalla del RC). Desde ahí, RTMP (¿soportado por el Neo? sin confirmar → Experimento E1) o captura de pantalla.
- ❌ **El control remoto NO se conecta al PC.** No existe DJI Fly de escritorio. El RC sirve para pilotar manualmente, nada más.

## Estado del entorno (verificado 2026-07-09)

| Herramienta | Estado |
|---|---|
| Python 3.14 (`C:\Python314\python.exe`) | ✅ wheels de OpenCV/numpy disponibles |
| git, node | ✅ |
| ffmpeg / ffprobe | ❌ no instalado |
| Docker | ❌ no instalado |
| WSL2 | instalado, **sin ninguna distro Linux** |

**Implicación:** ROS 1 + RViz + ORB-SLAM3 requieren Linux → hay que instalar **Ubuntu 20.04** en WSL2 (~20 min). Ojo: `wsl --install -d Ubuntu` trae la LTS más reciente, que **no sirve** para Noetic; hay que pedir 20.04 explícitamente. **Pero no antes de validar el vídeo** con Python + OpenCV en Windows (ver abajo).

## Estado actual del proyecto

- ✅ Investigación documentada en `infoDJI/` (10 archivos).
- ✅ `data/raw/` creada para los vídeos originales.
- ⏳ **Pendiente:** el usuario grabará **únicamente su cuarto** y dejará el vídeo en `data/raw/`.
- ⬜ Nada de código todavía. El repositorio no está bajo git (sugerir `git init` cuando convenga).

## Siguiente paso exacto (retomar aquí)

Cuando aparezca un `.mp4` en `data/raw/`:

1. **Diagnóstico previo, sin instalar nada pesado.** Con Python + OpenCV en Windows:
   - leer resolución, fps, códec y duración reales;
   - correr un test de **densidad y seguimiento de features** (ORB/Shi-Tomasi + optical flow) fotograma a fotograma;
   - estimar si hay **paralaje** suficiente (traslación real, no solo rotación).
   - Objetivo: responder *¿este vídeo tiene textura y movimiento suficientes para que un SLAM lo procese?* en minutos, no en horas.
2. **Si el diagnóstico es bueno:** instalar Ubuntu 20.04 en WSL2 + ROS Noetic → Experimentos E2 (vídeo → ROS 1) y E3 (calibración + SLAM).
3. **Si es malo:** ajustar la técnica de grabación (ver `GRABACION_CHECKLIST.md`) y repetir. Mucho más barato que descubrirlo tras instalar el stack completo.

Los 9 experimentos con criterios de éxito medibles están en [`infoDJI/EXPERIMENTS_TODO.md`](infoDJI/EXPERIMENTS_TODO.md).

## Recordatorio crítico sobre la grabación

El error que arruina la toma entera: **rotar sin trasladarse**. El SLAM monocular necesita paralaje para inicializar. Ver [`GRABACION_CHECKLIST.md`](GRABACION_CHECKLIST.md).

También: **medir el cuarto con cinta métrica** y dejar un objeto de tamaño conocido a la vista. Sin referencia métrica, el mapa sale en unidades arbitrarias y "avanza 50 cm" nunca significa nada.
