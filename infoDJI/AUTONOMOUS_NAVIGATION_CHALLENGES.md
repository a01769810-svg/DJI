# Retos de navegación autónoma

## El bloqueo crítico

Aunque el sistema llegue a producir:

- mapa 3D;
- localización;
- reconocimiento semántico;
- waypoints;
- rutas planificadas;
- detección de obstáculos;
- frontend web;

existe un problema crítico: **no hay una API oficial conocida para mandar al DJI Neo original órdenes programáticas** (avanzar, girar, subir, ir a XYZ, seguir una trayectoria). Ver [DJI_NEO_LIMITATIONS.md](DJI_NEO_LIMITATIONS.md).

Además, el Neo **no tiene evasión de obstáculos multidireccional**: aunque se pudiera comandar, no hay red de seguridad a bordo para interiores.

## Consecuencia de diseño: capas estrictamente separadas

```text
A. Perception and mapping layer      (vídeo → SLAM → mapa)
B. Localization layer                (pose en house_map)
C. Semantic world model              (habitaciones, waypoints, objetos)
D. Path-planning layer               (rutas 3D sobre el mapa)
E. Drone-control adapter             (ejecución en un dron concreto)
```

Las capas A–D son **independientes del dron** y tienen valor por sí mismas. La capa E es la única acoplada al hardware y debe ser un **adaptador modular** con una interfaz estable (p. ej. `follow_path(Path)`, `goto(PoseStamped)`, `hold()`, `land()`), con implementaciones intercambiables:

- **Neo adapter** — solo si algún día se encuentra una vía fiable (hoy: ❌ no existe).
- **PX4 adapter** — plataforma abierta con offboard control documentado (https://docs.px4.io/main/en/advanced/computer_vision).
- **Otro dron con SDK** (p. ej. modelos DJI soportados por MSDK V5).
- **Simulador** — Gazebo / PX4 SITL: permite desarrollar y demostrar D+E completas **hoy**, sin hardware.

**No acoplar el proyecto al Neo.** El Neo es la plataforma de captura de la fase 1, no el ejecutor de la fase de navegación.

## Retos técnicos por capa (aun con un dron controlable)

### Localización (B)
- Relocalización visual robusta al arrancar en cualquier punto de la casa.
- Deriva del SLAM monocular; escala métrica correcta (crítica para "avanza 50 cm").
- Zonas de poca textura (paredes lisas) y cambios de iluminación día/noche.

### Planificación (D)
- Planificación **3D real** (la casa tiene 3 pisos; las escaleras son corredores 3D estrechos).
- Márgenes de seguridad: pasillos y puertas dejan poco espacio; el mapa debe inflarse con el radio del dron + margen de error de localización.
- Obstáculos dinámicos (personas, mascotas, puertas que se cierran): requiere percepción en vivo, no solo el mapa estático.

### Ejecución (E)
- Control en lazo cerrado: pose estimada por visión con latencia + ruido → el controlador debe tolerarlo.
- Fallos seguros: pérdida de tracking ⇒ hover/aterrizaje inmediato, nunca "seguir a ciegas".
- Escaleras: la zona más peligrosa (geometría estrecha, turbulencia propia, tracking difícil — ver [HOUSE_MAPPING_ARCHITECTURE.md](HOUSE_MAPPING_ARCHITECTURE.md)).

## Estrategia recomendada

1. **Fase 1 (ahora):** Neo como sensor + capas A–C + RViz. Vuelo siempre manual.
2. **Fase 2:** capa D (planificación) demostrada **en simulación** sobre el mapa real de la casa: seleccionar waypoint en RViz/web → ruta calculada y visualizada.
3. **Fase 3:** capa E sobre simulador (PX4 SITL/Gazebo) con el mapa real: un dron simulado navega la casa.
4. **Fase 4 (futuro):** hardware real controlable (PX4 u otro dron con SDK) — o el Neo únicamente si aparece una vía fiable y demostrada.

Esto permite que **todo el valor del proyecto (mapa, semántica, world model, web) se materialice sin resolver el bloqueo del control del Neo**, y deja la puerta abierta a cualquier plataforma futura.
