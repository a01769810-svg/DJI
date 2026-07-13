# Arquitectura ROS 1 ↔ RViz ↔ Three.js

## Principio: ROS 1 es la fuente de verdad

**NO** diseñar el sistema como:

```text
RViz → exportar directamente → Three.js     ❌
```

RViz no es una fuente de datos — es solo un visualizador. La arquitectura correcta:

```text
                    ROS 1 / WORLD MODEL
                           |
              +------------+------------+
              |                         |
            RViz                     Three.js
      ingeniería/debug         interfaz web final
```

Ambos visualizadores consumen los **mismos topics** del world model. Cualquier dato que se quiera ver en la web debe existir primero como topic/estado en ROS.

## Distro y entorno

- **ROS Noetic Ninjemys** sobre **Ubuntu 20.04 (Focal)**. Es la única combinación soportada: Noetic no tiene paquetes oficiales para 22.04 en adelante.
- Build system: `catkin` (`catkin_make` o `catkin build`). No `colcon`.
- Cliente Python: `rospy` (Python 3.8, fijado por la distro). No `rclpy`.
- ⚠️ **Noetic es EOL desde mayo de 2025** y Focal salió de soporte estándar en abril de 2025. Decisión consciente del proyecto: aceptable para investigación local, no para exposición a red.

## Topics potenciales

```text
/map                  # mapa (point cloud / ocupación)
/tf                   # árbol de transformadas dinámico
/tf_static            # transformadas fijas
/drone/pose           # pose estimada del dron
/drone/path           # trayectoria recorrida
/camera/image         # vídeo de la cámara principal
/point_cloud          # nube de puntos del SLAM
/obstacles            # obstáculos detectados
/planned_path         # ruta planificada
/waypoints            # waypoints semánticos
/rooms                # habitaciones / regiones
/semantic_objects     # objetos reconocidos (puertas, muebles…)
```

Los tipos de mensaje (`sensor_msgs/Image`, `PointCloud2`, `visualization_msgs/MarkerArray`, `nav_msgs/Path`, `geometry_msgs/PoseStamped`) son idénticos en ROS 1 y ROS 2, igual que TF2. La arquitectura de topics no cambia — solo el runtime y las herramientas.

## RViz (fase de ingeniería / debug)

RViz (el de ROS 1, comando `rviz`) se usa para depurar y validar:

- TF frames;
- pose del dron;
- modelo 3D;
- point clouds;
- SLAM;
- mapas;
- obstáculos;
- rutas;
- waypoints;
- markers.

Guía oficial: http://wiki.ros.org/rviz

**El hito 1 del proyecto termina en RViz**: mapa + pose visibles ahí antes de escribir una sola línea de la web.

## Por qué ROS 1 favorece este stack

No es un downgrade para este proyecto en concreto. Las piezas clave son nativas de ROS 1:

| Pieza | Situación en ROS 1 |
|---|---|
| **ORB-SLAM3** | El repo oficial trae ejemplos ROS 1 (`Examples/ROS/ORB_SLAM3`). En ROS 2 dependes de forks de la comunidad. |
| **RTAB-Map** (`rtabmap_ros`) | Maduro y muy documentado en Noetic. |
| **`octomap_server`** | Nativo de ROS 1; es la vía para el mapa 3D de ocupación (E9). |
| **`rosbridge_suite` / `roslibjs` / `ros3djs`** | Proyectos de la era ROS 1. `ros3djs` está escrito contra ROS 1. |
| **MAVROS** (PX4 SITL, fase 2) | La ruta clásica y mejor documentada es ROS 1 + MAVROS. |

Lo que se pierde: Nav2 (que es 2D y no nos sirve — el planificador va sobre OctoMap con OMPL/A\*) y las actualizaciones de seguridad.

## Web final (fase posterior)

Stack candidato:

- Next.js
- React
- Three.js — https://threejs.org/
- React Three Fiber
- WebSockets

### Puente ROS 1 → Web

Dos opciones (decisión pendiente, no bloqueante para el hito 1):

1. **rosbridge_suite** (http://wiki.ros.org/rosbridge_suite) — expone topics por WebSocket con protocolo JSON estándar; en el cliente se usa `roslibjs`, con `ros3djs` (https://github.com/RobotWebTools/ros3djs) como referencia de visualización 3D web sobre ROS.
   - Pros: inmediato, estándar, sin backend propio. En ROS 1 es el camino original de estas librerías, así que los ejemplos funcionan tal cual.
   - Contras: JSON es pesado para point clouds grandes; menos control.
2. **Backend propio** (nodo ROS → servidor WebSocket con mensajes binarios/proto propios, con decimación/compresión de point clouds).
   - Pros: control total de rendimiento y del formato para Three.js.
   - Contras: más trabajo.

Recomendación: empezar con **rosbridge_suite** para prototipar la web; migrar a backend propio solo si el rendimiento con point clouds lo exige (probablemente sí para nubes densas — decimar/voxelizar antes de enviar en cualquier caso).

## Vista global del sistema

```text
              DJI NEO / FUTURE DRONE
                       |
                       v
                 VIDEO / SENSORS
                       |
                       v
                    ROS 1
                       |
        +--------------+--------------+
        |              |              |
        v              v              v
      SLAM        AI SEMANTICS    LOCALIZATION
        |              |              |
        +--------------+--------------+
                       |
                       v
                 WORLD MODEL
                       |
          +------------+------------+
          |                         |
          v                         v
        RViz                    Navigation
       Debug                     Planner
          |                         |
          +------------+------------+
                       |
                       v
                 WebSocket/API
                       |
                       v
              Three.js Web App
```

## Notas de implementación

- **Distro de referencia: Noetic / Ubuntu 20.04.** Al instalar WSL2, pedir la versión explícitamente (`wsl --install -d Ubuntu-20.04`); el `-d Ubuntu` por defecto instala la LTS más reciente, incompatible con Noetic.
- ROS corre nativamente mal en Windows para este stack; plan práctico: **WSL2 con Ubuntu 20.04** o una máquina Linux dedicada. RViz dentro de WSL2 funciona con WSLg en Windows 11. (🧪 validar rendimiento con point clouds grandes).
- Noetic fija **Python 3.8**. La detección semántica (YOLO, E5) debe correr en un proceso/venv separado con su propio Python y comunicarse por topics — no intentar meter torch moderno dentro del intérprete de `rospy`.
- El world model semántico (habitaciones, waypoints) debe persistirse fuera de ROS (YAML/JSON) y publicarse al arrancar, para que sobreviva reinicios.
