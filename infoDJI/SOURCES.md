# Fuentes

Fuentes oficiales y técnicas de esta investigación. Fecha de compilación: **2026-07-09** — verificar vigencia antes de decisiones importantes (el soporte de SDK y las funciones de DJI Fly cambian con actualizaciones).

## DJI — oficiales

| Recurso | URL | Uso en el proyecto |
|---|---|---|
| Página oficial del DJI Neo | https://www.dji.com/neo | Capacidades del producto, cámara, modos de vuelo |
| Soporte DJI Neo | https://www.dji.com/support/product/neo | FAQ y soporte oficial |
| Descargas y manuales DJI Neo | https://www.dji.com/neo/downloads | **Manual oficial: referencia canónica de sensores y especificaciones** |
| DJI Mobile SDK V5 — introducción | https://developer.dji.com/doc/mobile-sdk-tutorial/en/basic-introduction/msdk-introduction.html | Evidencia de que el Neo **no** está entre las aeronaves soportadas |

## SLAM / visión / drones

| Recurso | URL | Uso |
|---|---|---|
| ORB-SLAM3 (paper, arXiv) | https://arxiv.org/abs/2007.11898 | SLAM visual candidato principal |
| PX4 — Computer Vision / VIO | https://docs.px4.io/main/en/advanced/computer_vision | Referencia de VIO y plataforma futura controlable |

Otras tecnologías relevantes (documentación en sus sitios/repos oficiales): RTAB-Map, OpenVSLAM (u equivalentes), OpenCV, YOLO y modelos de detección, modelos de estimación monocular de profundidad.

## ROS 1 / visualización

El proyecto usa **ROS 1 Noetic** sobre Ubuntu 20.04. Ver [ROS_RVIZ_THREEJS_ARCHITECTURE.md](ROS_RVIZ_THREEJS_ARCHITECTURE.md).

| Recurso | URL | Uso |
|---|---|---|
| ROS Noetic (instalación y estado) | http://wiki.ros.org/noetic | Distro del proyecto. ⚠️ EOL desde mayo 2025 |
| RViz (ROS 1) | http://wiki.ros.org/rviz | Visualización de debug |
| rosbridge_suite (ROS 1) | http://wiki.ros.org/rosbridge_suite | Puente WebSocket ROS ↔ web |
| Three.js | https://threejs.org/ | Render 3D en la web |
| ros3djs (RobotWebTools) | https://github.com/RobotWebTools/ros3djs | Referencia de visualización ROS en el navegador |

## Conceptos ROS usados en la arquitectura

TF2, `sensor_msgs/PointCloud2`, `visualization_msgs/Marker` / `MarkerArray`, `nav_msgs/Path`, `geometry_msgs/PoseStamped` — documentados en http://wiki.ros.org/. Estos tipos son comunes a ROS 1 y ROS 2; lo que cambia es el runtime (`rospy`/`catkin`, no `rclpy`/`colcon`).

## Pendiente de investigar (sin fuente confirmada aún)

- Compatibilidad exacta del **RTMP de DJI Fly con el DJI Neo** (versión actual de la app) — 🧪 Experimento 1.
- Formato y contenido de los **logs de vuelo** de DJI Fly para el Neo — 🧪 Experimento.
- Proyectos open-source de la comunidad sobre protocolos DJI aplicables a la generación de hardware del Neo — evaluar caso por caso (licencia, mantenimiento, aplicabilidad) antes de citarlos como fuente.
