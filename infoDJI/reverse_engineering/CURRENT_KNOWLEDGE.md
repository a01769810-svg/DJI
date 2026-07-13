# Conocimiento actual — punto de partida

> Estado a 2026-07-10. Base sobre la que arranca la investigación de control programático. Se actualiza a medida que los experimentos produzcan `[OBSERVED]` / `[CONFIRMED]` / `[FAILED]`.

## [CONFIRMED] — lo que damos por establecido

- El **DJI Neo original no está soportado por DJI Mobile SDK V5**. Respuesta oficial del equipo SDK de DJI (issue #725, marzo 2026): *"the MSDK does not support the Neo series models such as the Neo 1 and Neo 2, and there are currently no relevant support plans"*.
- **No existe API oficial pública** de Virtual Stick / control programático para el Neo.
- **No existe un SDK tipo Tello** documentado para el Neo.
- El **DJI Tello sí** permite control programático por Wi-Fi/UDP (comandos de texto a `192.168.10.1:8889`) **porque fue diseñado explícitamente para ello** (producto educativo Ryze). No es extrapolable al Neo.
- **DJI Fly controla el Neo por conexión inalámbrica** → **necesariamente existe un protocolo de comunicación** `DJI Fly / controlador ↔ DJI Neo`. Esa cadena es el objeto central de la investigación.
- DJI usa históricamente protocolos internos relacionados con **DUML / MB protocol** en diversos productos.
- Proyectos de RE conocidos: `o-gs/dji-firmware-tools`, `fvantienen/dji_rev`, `samuelsadok/dji_protocol`, e investigación académica sobre DUML (tesis Christof 2021).
- **Ningún proyecto público encontrado hasta ahora demuestra control programático del DJI Neo original.**
- La comunicación Wi-Fi puede ir protegida con **WPA2/CCMP** u otras capas propietarias.
- **Extraer firmware ≠ disponer de un canal de control.** Son cosas distintas.
- **RTMP es solo salida de vídeo**, no proporciona control ni telemetría.

## [UNKNOWN] — lo que debemos determinar

1. Qué protocolo exacto usa el Neo cuando se controla desde DJI Fly por Wi-Fi.
2. Si existe DUML en algún nivel del enlace.
3. Si los comandos viajan directamente por IP/UDP/TCP.
4. Si hay protocolos propietarios adicionales.
5. Si vídeo y comandos viajan por canales diferentes.
6. Qué servicios, puertos y endpoints expone el Neo.
7. Si el protocolo está cifrado adicionalmente sobre WPA2.
8. Si hay autenticación de sesión.
9. Si hay nonces, claves efímeras, challenge-response o firmas.
10. Si una sesión válida de DJI Fly puede observarse desde el propio dispositivo Android.
11. Si pueden extraerse logs de DJI Fly útiles para identificar comandos.
12. Si es posible instrumentar DJI Fly (dispositivo de laboratorio propio) para observar sus llamadas y tráfico.
13. Si los APK contienen clases, strings, protobufs, schemas o librerías nativas relacionadas con el Neo.
14. Si el firmware contiene command IDs, tablas DUML, endpoints, nombres de servicios o estructuras reutilizables.
15. Si DJI Assistant 2 revela alguna interfaz adicional.
16. Si existen trabajos no indexados en comunidades chinas, japonesas, rusas, alemanas, etc.
17. Si hay hardware adicional aprovechable: debug UART, USB, test pads, SWD/JTAG.
18. Si la comunicación por RC-N3 / Goggles ofrece una superficie de investigación distinta.

> Los resultados de la investigación mundial (FASE 1) y de los experimentos irán convirtiendo estos `[UNKNOWN]` en hallazgos etiquetados. Ver `FINDINGS.md` y `EXPERIMENT_LOG.md`.
