# Experimentos pendientes

Cada experimento tiene un criterio de éxito medible. Regla del proyecto: nada pasa de 🧪 experimental a ✅ confirmado sin superar su criterio.

## Prioridad del proyecto

> Demostrar **vídeo del DJI Neo → procesamiento externo → ROS 1 → mapa/localización → visualización en RViz** antes de intentar navegación autónoma real.

Los experimentos E1–E4 componen exactamente ese hito.

---

## E1 — Extraer vídeo del Neo hacia el PC ⭐ (siguiente experimento recomendado)

**Pregunta:** ¿por qué vía y con qué latencia/calidad puede llegar el vídeo del Neo a un PC?

**Pasos:**
1. Revisar en DJI Fly (versión actual, con el Neo conectado) si aparece la opción de transmisión RTMP personalizada.
2. Si existe: montar un servidor RTMP local (MediaMTX o nginx-rtmp) y transmitir; medir latencia, resolución y estabilidad.
3. Si no existe: probar plan B — captura de pantalla del móvil (scrcpy en Android, o mirroring + capturadora).
4. En paralelo (plan C, siempre disponible): copiar un vídeo grabado a bordo y usarlo como fuente offline.

**Éxito:** vídeo del Neo reproducible en el PC por al menos una vía; documentar latencia y calidad de cada vía probada. *(El plan C ya basta para E2–E4 offline.)*

## E2 — Vídeo → ROS 1

**Pregunta:** ¿podemos publicar ese vídeo como `sensor_msgs/Image` en ROS 1?

**Pasos:** entorno ROS Noetic (WSL2 con **Ubuntu 20.04** o máquina Linux); nodo `rospy` que lea la fuente (RTMP/captura/archivo) con OpenCV/GStreamer y publique `/camera/image` + `camera_info` vía `cv_bridge`; verificar en RViz o `rqt_image_view`.

**Éxito:** imagen del Neo visible en RViz a framerate estable.

## E3 — Calibración + SLAM con vídeo del Neo

**Pregunta:** ¿un SLAM visual (ORB-SLAM3 / RTAB-Map / equivalente) mantiene tracking con el vídeo del Neo en interiores?

**Pasos:**
1. Calibrar intrínsecos de la cámara (patrón de tablero grabado con el Neo, o autocalibración).
2. Grabar una pasada lenta por **una sola habitación** bien iluminada.
3. Ejecutar el SLAM offline; evaluar tracking, loop closure y point cloud.
4. Repetir con: pasillo, y luego escaleras (el caso difícil).

**Éxito:** trayectoria + point cloud coherentes de al menos una habitación, visualizados en RViz (`/tf`, `/drone/pose`, `/point_cloud`).

## E4 — Mapa multi-habitación con Z real (hito 1 completo)

**Pregunta:** ¿podemos unir varias habitaciones y al menos dos pisos en un único mapa `house_map`?

**Pasos:** grabar recorrido continuo habitación→pasillo→escalera→piso 2; resolver escala métrica con una referencia medida; persistir y recargar el mapa; relocalizar el dron en un mapa previamente construido.

**Éxito:** mapa único con dos pisos y alturas Z correctas (±20 %), visible en RViz; relocalización funcional en el mapa cargado.

## E5 — Waypoints semánticos

**Pasos:** etiquetar manualmente habitaciones sobre el mapa de E4 (YAML/JSON); publicarlas como `MarkerArray` en `/waypoints` y `/rooms`; después, probar detección automática (YOLO sobre keyframes → asociar objetos a posiciones del mapa → `/semantic_objects`).

**Éxito:** waypoints con nombre visibles en RViz en sus posiciones reales.

## E6 — Puente web (Three.js)

**Pasos:** rosbridge_suite + página React Three Fiber mínima que muestre point cloud (decimado), pose del dron y waypoints.

**Éxito:** el mismo world model de RViz visible en el navegador.

## E7 — Logs de vuelo de DJI Fly (paralelo, no bloqueante)

**Pregunta:** ¿qué telemetría del Neo contienen los logs y sirve para validar el SLAM?

**Pasos:** exportar logs tras un vuelo; analizar campos disponibles (altitud, actitud, posición relativa…); comparar offline contra la trayectoria del SLAM.

**Éxito:** inventario documentado de campos disponibles y su fiabilidad. *(Resultado negativo también es útil: cierra la vía.)*

## E8 — Investigación de control del Neo (exploratorio, baja prioridad)

**Pregunta:** ¿existe alguna vía no oficial mínimamente fiable de telemetría en vivo o control?

**Pasos:** revisar DJI Assistant 2 con el Neo; inventariar proyectos open-source de protocolos DJI y su aplicabilidad a esta generación de hardware; solo entonces valorar análisis de tráfico.

**Advertencia:** no invertir tiempo significativo aquí hasta que E1–E6 estén cerrados. **No asumir éxito.** Resultado esperado más probable: confirmar la limitación y reforzar la ruta PX4/simulador (ver [AUTONOMOUS_NAVIGATION_CHALLENGES.md](AUTONOMOUS_NAVIGATION_CHALLENGES.md)).

## E9 — Planificación en simulación (fase 2)

**Pasos:** sobre el mapa de E4, planificador 3D (p. ej. OMPL/A* sobre OctoMap) → `/planned_path`; selección de waypoint desde RViz; después, dron simulado (PX4 SITL + Gazebo) siguiendo la ruta.

**Éxito:** ruta 3D válida entre dos habitaciones de distinto piso, visualizada en RViz; dron simulado la recorre sin colisiones.

---

## Orden recomendado

```text
E1 → E2 → E3 → E4 (hito 1) → E5 → E6 → E9
          E7 en paralelo desde E3
          E8 solo al final, sin expectativas
```
