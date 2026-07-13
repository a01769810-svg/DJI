# Arquitectura de mapeo de la casa (3 pisos)

## Principio de diseño: un único mundo 3D global

El mapa **no** se modela como tres mapas 2D apilados, sino como **un único mundo tridimensional global** desde el principio, con un solo frame raíz:

- Frame global: **`house_map`**
- Todas las posiciones son XYZ reales en metros dentro de ese frame (Z = altura real).

Ejemplo de posiciones:

```text
Sala:              x = 2.0   y = 3.0   z = 1.5
Oficina piso 2:    x = 5.0   y = 4.0   z = 4.8
Terraza piso 3:    x = 7.0   y = 6.0   z = 8.2
```

## Jerarquía semántica de la casa

La estructura lógica (no de frames TF, sino del world model semántico):

```text
house_map
├── floor_1
│   ├── living_room
│   ├── kitchen
│   ├── dining_room
│   └── stairs_1_2
├── floor_2
│   ├── bedrooms
│   ├── office
│   └── stairs_2_3
└── floor_3
    └── terrace
```

Cada habitación/zona es un **waypoint semántico**: nombre + posición XYZ (+ opcionalmente un volumen/región que la delimita). Las escaleras se modelan como zonas de transición entre pisos.

## Pipeline de percepción y mapeo

```text
DJI Neo / cámara
→ Video stream
→ ROS 1
→ Visual SLAM / VIO
→ TF
→ pose estimada del dron
→ mapa 3D
→ detección semántica
→ waypoints
→ planificación
→ RViz
```

### Capas del sistema (separación estricta)

| Capa | Responsabilidad | Estado |
|---|---|---|
| A. Perception & mapping | vídeo → SLAM → point cloud / mesh | Implementable ya (offline) |
| B. Localization | pose del dron en `house_map` (relocalization sobre mapa previo) | Implementable tras A |
| C. Semantic world model | habitaciones, puertas, muebles, waypoints | Implementable sobre A |
| D. Path-planning | rutas 3D entre waypoints evitando obstáculos del mapa | Implementable (simulable) |
| E. Drone-control adapter | ejecutar rutas en un dron real | **Bloqueado con el Neo** — interfaz modular |

## Frames TF propuestos

```text
house_map              (frame global fijo)
└── odom               (opcional, deriva local del SLAM)
    └── base_link      (pose del dron)
        └── camera_link
```

## Flujo de trabajo de mapeo (fase inicial, vuelo manual)

1. Volar manualmente el Neo por la casa, piso por piso, grabando vídeo (pasadas lentas, solapadas, con giros suaves).
2. Procesar el vídeo con SLAM (offline primero) → trayectoria + point cloud.
3. Unir sesiones/pisos: las escaleras son las zonas de conexión — grabar tomas continuas subiendo/bajando para que el SLAM enlace pisos en un solo mapa con Z real.
4. Resolver la escala (ambigüedad monocular): referencia métrica manual (p. ej. medir un pasillo) o profundidad monocular.
5. Etiquetar habitaciones y crear waypoints semánticos (manual al inicio; detección automática después).
6. Persistir el mapa + waypoints en disco (formato del SLAM elegido + YAML/JSON propio para la capa semántica).

## Zona crítica: escaleras

Las escaleras serán una de las zonas más difíciles debido a:

- paredes cercanas;
- barandales;
- cambios de altura;
- cambios de iluminación;
- techos;
- geometría estrecha;
- personas u obstáculos dinámicos.

Mitigaciones (🧪 a validar): pasadas múltiples y lentas, iluminación encendida y constante, grabar subida y bajada, verificar loop closure entre pisos; si el SLAM se pierde sistemáticamente, tratar las escaleras como *enlaces topológicos* entre submapas de piso en lugar de exigir tracking continuo.

## Representaciones de datos en ROS 1

- Mapa denso: `sensor_msgs/PointCloud2` (y/o OctoMap para planificación con ocupación 3D).
- Pose del dron: `geometry_msgs/PoseStamped` + TF.
- Trayectoria: `nav_msgs/Path`.
- Waypoints y objetos semánticos: `visualization_msgs/Marker` / `MarkerArray` + mensajes/formato propio para la semántica persistente.

La lista completa de topics y el reparto RViz/Three.js está en [ROS_RVIZ_THREEJS_ARCHITECTURE.md](ROS_RVIZ_THREEJS_ARCHITECTURE.md).
