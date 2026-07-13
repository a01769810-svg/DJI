# DJI Neo — Ingeniería inversa para control programático

> **Prioridad absoluta del proyecto** (desde 2026-07-10). Este directorio documenta la investigación experimental para descubrir si el **DJI Neo original** puede controlarse desde software propio (despegar, aterrizar, throttle/yaw/pitch/roll, movimientos relativos, y eventualmente XYZ/waypoints + telemetría), para integrarlo después con **ROS 1 Noetic**.

## Postura del proyecto (regla fundamental)

Prohibido afirmar *"el DJI Neo es imposible de controlar programáticamente"*. La conclusión válida hoy es:

> **[NO CONFIRMED PATH]** — Actualmente no existe una vía pública, documentada y demostrada para controlar programáticamente el DJI Neo original. Nuestro objetivo es investigar experimentalmente si puede descubrirse una.

No se abandona una línea de investigación solo porque no exista documentación oficial. Se avanza mediante: (1) evidencia, (2) experimentos, (3) comparación de paquetes, (4) análisis de software, (5) análisis de firmware, (6) comparación con otros drones DJI, (7) investigación multilingüe, (8) reproducción independiente.

## Alcance ético y legal (no negociable)

- Solo **hardware propio**, en **entorno privado y controlado**.
- Propósito: **interoperabilidad e investigación** del propio dispositivo.
- ❌ NO atacar infraestructura de DJI · ❌ NO jamming · ❌ NO afectar drones ajenos · ❌ NO interferir redes/dispositivos de terceros · ❌ NO desactivar geofencing ni protecciones regulatorias como objetivo.
- ❌ NO flashing, modificación de firmware ni cambios físicos irreversibles **sin detenerse antes, explicarlo y obtener aprobación explícita**.
- Seguridad física en pruebas: retirar hélices cuando sea adecuado, protectores, lejos de personas/animales, energía/duración limitadas, corte de potencia inmediato a mano.

## Sistema de etiquetas (obligatorio en todos los documentos)

| Etiqueta | Significado |
|---|---|
| `[CONFIRMED]` | Documentado por fuente primaria fiable. |
| `[OBSERVED]` | Visto en una captura, demo o reproducción pública concreta. |
| `[INFERRED]` | Deducción razonada a partir de evidencia indirecta. |
| `[EXPERIMENTAL]` | Alguien lo ha probado, pero sin garantía / no reproducido por nosotros. |
| `[UNKNOWN]` | Aún por determinar. |
| `[FAILED]` | Intentado y no funcionó. |
| `[BLOCKED]` | Barrera conocida que impide avanzar por esa vía. |

**Nunca** presentar una inferencia como hecho.

## Estructura del directorio

| Archivo | Contenido |
|---|---|
| `README.md` | Este archivo: postura, ética, etiquetas, índice. |
| `CURRENT_KNOWLEDGE.md` | Lo que sabemos hoy, clasificado `[CONFIRMED]` / `[UNKNOWN]`. |
| `ATTACK_SURFACE.md` | Superficie de investigación + **matriz de rutas** (evidencia/dificultad/probabilidad/riesgo/próximo experimento). |
| `NETWORK_RESEARCH.md` | Enlace Neo↔DJI Fly: IPs, puertos, protocolos, captura de tráfico. |
| `DJI_FLY_RESEARCH.md` | Análisis estático/dinámico de la app DJI Fly (APK, .so, DUML, cadena comando→transporte). |
| `DUML_RESEARCH.md` | Protocolo DUML/MB, command sets/IDs, framing, y reutilización entre productos DJI. |
| `FIRMWARE_RESEARCH.md` | Obtención/análisis de firmware del Neo (formato, cifrado, herramientas, strings). |
| `HARDWARE_INTERFACES.md` | Silicio (SoC/FC/WiFi), FCC, teardown, interfaces de debug (UART/SWD/JTAG/USB). |
| `COMMUNITY_RESEARCH.md` | Hallazgos de comunidades multilingües (EN/ZH/JA/DE/FR/ES/SV/HI/RU). |
| `EXPERIMENT_PLAN.md` | Plan de experimentos con criterios de éxito/fracaso. |
| `EXPERIMENT_LOG.md` | Bitácora cronológica de experimentos ejecutados y resultados. |
| `FINDINGS.md` | Hallazgos consolidados y conclusiones vivas. |
| `SOURCES.md` | Todas las fuentes con URL y calidad. |

## Fases de trabajo

- **FASE 0** — Crear esta documentación. ✅ en curso.
- **FASE 1** — Investigación mundial exhaustiva multilingüe.
- **FASE 2** — Análisis de la superficie de comunicación (requiere el Neo físico).
- **FASE 3** — DJI Fly (análisis estático y dinámico).
- **FASE 4** — DUML y protocolos DJI.
- **FASE 5** — Firmware.
- **FASE 6** — Hardware / interfaces de debug.
- **FASE 7** — Primer objetivo mínimo (observar/reproducir un comando, o leer telemetría).

## Primer objetivo mínimo (no waypoints)

El primer éxito real será UNO de: (A) observar un comando de control identificable; (B) reproducir un paquete no peligroso; (C) leer telemetría en vivo; (D) identificar claramente el protocolo; (E) provocar un cambio reproducible en el dron desde software propio; (F) controlar un único eje con el dron asegurado y sin hélices. Después: takeoff/land/yaw/pitch/roll/throttle. Solo mucho después: position/XYZ/trayectorias/waypoints/ROS 1.

## Integración futura con ROS 1 (si hay control)

Nodo modular `dji_neo_driver` con el protocolo aislado tras un *adapter* intercambiable:

```
ROS 1  →  dji_neo_driver  →  protocol adapter  →  DJI Neo
```

Interfaces objetivo: `/cmd_vel`, `/neo/takeoff`, `/neo/land`, `/neo/state`, `/neo/battery`, `/neo/pose`, `/neo/telemetry`.
