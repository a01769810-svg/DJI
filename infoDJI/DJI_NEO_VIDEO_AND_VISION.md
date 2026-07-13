# DJI Neo — Vídeo y pipeline de visión

El vídeo de la cámara principal es el **único canal de datos explotable de forma realista** en el Neo para este proyecto. Todo el sistema de percepción se construye sobre él.

## Obtención del vídeo

### ✅ Confirmado

- El Neo transmite vídeo en vivo de su cámara principal a DJI Fly.
- DJI Fly dispone de posibilidades de streaming, incluyendo **RTMP personalizado en productos compatibles**.
- El Neo graba vídeo a bordo (los archivos grabados siempre están disponibles para procesamiento offline).

### 🧪 Experimental — vías candidatas para llevar el vídeo al PC (Experimento 1)

Ordenadas de más a menos deseable; hay que validar cuáles funcionan con el Neo y con qué latencia:

| Vía | Tiempo real | Notas |
|---|---|---|
| RTMP desde DJI Fly a servidor propio (nginx-rtmp / MediaMTX) | Sí (latencia por medir) | **Confirmar primero que DJI Fly ofrece RTMP con el Neo** |
| Captura/mirroring de pantalla del móvil (scrcpy + captura, o AirPlay/Chromecast → capturadora) | Sí (latencia media) | Plan B robusto; degrada algo la calidad |
| Vídeo grabado a bordo, procesado offline | No | Siempre disponible; suficiente para mapeo offline (hito 1) |

**Nota clave:** el hito 1 (mapa en RViz) **no requiere tiempo real**. El mapeo offline con vídeo grabado ya lo demuestra. El tiempo real solo es necesario para localización en vivo y navegación futura.

## Usos del vídeo en el pipeline

La cámara principal sirve como entrada para el pipeline externo de:

- visión artificial;
- detección de personas y objetos;
- segmentación;
- reconocimiento semántico (habitaciones, puertas, muebles);
- SLAM visual;
- estimación monocular de profundidad;
- localización visual;
- reconstrucción 3D (point clouds / meshes).

## Arquitectura del flujo de vídeo

```text
DJI Neo → DJI Fly / vídeo → RTMP o pipeline disponible → servidor/PC → ROS 1 → SLAM + IA → RViz + Web
```

En ROS 1, el punto de entrada será un nodo (`rospy` + `cv_bridge`) que publique `sensor_msgs/Image` (+ `camera_info`) desde la fuente que resulte viable (stream RTMP, dispositivo de captura o archivo de vídeo). Ese nodo aísla al resto del sistema de la vía concreta de obtención del vídeo.

## Consideraciones técnicas (🔧 inferidas, a validar)

- **Cámara monocular** → el SLAM monocular sufre ambigüedad de escala. Mitigaciones posibles: objetos de tamaño conocido en escena, medición manual de referencia, o modelos de profundidad monocular con escala aproximada.
- **Calibración de cámara**: será necesario calibrar intrínsecos (y distorsión) a partir del propio vídeo o con un patrón de tablero — DJI no publica los intrínsecos exactos utilizables directamente por SLAM.
- **Compresión y rolling shutter**: el vídeo comprimido (y una posible transmisión con artefactos) degrada el tracking de features; probar distintas resoluciones/bitrates.
- **Interiores**: texturas pobres (paredes lisas), cambios bruscos de iluminación y escaleras estrechas son los peores escenarios para SLAM visual (ver [AUTONOMOUS_NAVIGATION_CHALLENGES.md](AUTONOMOUS_NAVIGATION_CHALLENGES.md)).

## Tecnologías candidatas

- **SLAM**: ORB-SLAM3 ([paper](https://arxiv.org/abs/2007.11898)), RTAB-Map, OpenVSLAM u otros sistemas equivalentes.
- **Visión**: OpenCV, YOLO u otros modelos de detección, modelos de estimación monocular de profundidad.
- **Integración**: ROS 1 (Noetic), TF2, RViz, `PointCloud2`, `Marker`/`MarkerArray`, `nav_msgs/Path`.
- Referencia sobre VIO en drones: PX4 Computer Vision — https://docs.px4.io/main/en/advanced/computer_vision

Fuentes completas en [SOURCES.md](SOURCES.md).
