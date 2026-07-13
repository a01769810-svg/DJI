# Investigación de comunidad (multilingüe)

> Barrido en inglés, chino, ruso, alemán, francés, japonés y español. **Conclusión honesta y transversal a todos los idiomas:** el techo público del Neo es *parameter/region modding* (FCC/NFZ/altura/M-mode), **nunca** mando externo ni telemetría en vivo. Que no exista control del Neo **no es un hueco del inglés** — no existe en ningún idioma buscado.

## Lo que la comunidad SÍ ha logrado con el Neo

- **`[EXPERIMENTAL]`** **Drone-Hacks** y **Drone-Tweaks** soportan el Neo para edición de parámetros de firmware: FCC mode, eliminación de NFZ, límite de altura, aceleración (Drone-Tweaks vende una app Neo ~38 €). Herramientas cerradas y de pago, pero **prueban que una escritura DUML de parámetros alcanza físicamente el Neo**. Solo escriben parámetros estáticos; no transmiten telemetría ni emiten comandos de vuelo.
- **`[CONFIRMED]`** **DJI-FCC-HACK** (M4TH1EU): el mando N-series acepta un comando DUML de **escritura** por USB (CE→FCC), probado en Neo 2/Flip/Mini. Canal DUML escribible confirmado. Issue #25 pregunta por RC-N3+Neo 2, sin respuesta oficial.
- **`[OBSERVED]`** **HAM File Hack** funciona en el Neo (fpvwiki): un archivo `ham_cfg_support` habilita canales/RF extra. Toca RF/límites, no control.
- **`[OBSERVED]`** Foro chino **bbs.dji.com**: hilo *"Neo首次解锁M档"* (primer unlock del modo M/actitud del Neo). El cuerpo no es scrapeable (403 anti-bot); por el título + ecosistema, casi con seguridad es una edición de parámetros, no una API nueva.

## Lo que NO existe en ninguna comunidad

- **`[UNKNOWN]`** **Ningún pcap del Neo**, ninguna tabla de cmd_set/cmd_id de vuelo, ningún root shell — buscado en GitHub/Gitee, 52pojie, CSDN, Zhihu, 4PDA, Habr, Drohnen-Forum, foros japoneses/franceses. El único artefacto de protocolo concreto en abierto es el código de modelo **`wa521`** y el hecho de que su contenedor de firmware resiste los parsers actuales.
- **`[CONFIRMED]`** **DJIControlServer** y **RosettaDrone** (los puentes de control open-source más cercanos: REST 6-DOF / MAVLink) **dependen del MSDK** → muertos para el Neo. Útiles solo como referencia de arquitectura o para otro airframe (Mini 3 / Mavic 3E).

## Comunidades activas (dónde vigilar y publicar)

| Idioma | Sitio | Foco observado |
|---|---|---|
| EN | **NeoPilots** (neopilots.com) | MSDK/DJIControlServer, FCC enable; anti-bot 403 |
| EN | MavicPilots, RCGroups, IntoFPV | RE de WiFi de bajo nivel (genérico), teardown |
| ZH | **bbs.dji.com** (大疆社区) | unlock M-mode, mods de parámetros |
| RU | **4PDA** (hilo "DJI Neo / Neo 2 – Обсуждение") | FCC/CE region swaps, `ce_country_type` |
| DE | **Drohnen-Forum.de** (hilos "Hacks") | FCC unlocking |
| FR | YouTube (walkthroughs B3YOND) | FCC unlocking |
| — | **D3VL / B3YOND** (GitHub) | DUML moderno por WebSerial/WebUSB; Neo no es target aún |

## Recomendación

**Monitorizar** (no solo buscar puntualmente) los hilos del Neo por la palabra clave **`wa521`**, el primer pcap del Neo, o cualquier cmd_id de vuelo. Estrategia de aceleración: **publicar nuestra propia captura del Neo** (E-OBS-3/4) para atraer colaboración de RE — somos, hasta donde alcanza esta investigación, de los primeros en atacar el enlace del Neo con intención de control.

**Fuentes clave:** `Mobile-SDK-Android-V5` issue #725; `o-gs/dji-firmware-tools` issue #458; `M4TH1EU/DJI-FCC-HACK`; drone-hacks.com; `D3VL/B3YOND-WEB-APP`; bbs.dji.com tid 426571; 4pda.to topic 1094320; drohnen-forum.de; `dkapur17/DJIControlServer`; `RosettaDrone/rosettadrone`; fpvwiki (HAM hack). Lista completa en [`SOURCES.md`](SOURCES.md).
