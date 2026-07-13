# DJI Neo — Capacidades

Capacidades del DJI Neo original relevantes para este proyecto, clasificadas por nivel de confirmación (ver convención en [README.md](README.md)).

## ✅ Confirmado oficialmente

- **Cámara principal con transmisión de vídeo en vivo** hacia la app DJI Fly (y accesorios compatibles). El vídeo de la cámara principal es el insumo clave para todo el pipeline de visión de este proyecto.
- **Sistemas de posicionamiento inferiores**: el Neo incorpora visión inferior y detección infrarroja usadas *internamente* para estabilización, posicionamiento y aterrizaje (ver [DJI_NEO_SENSORS_AND_TELEMETRY.md](DJI_NEO_SENSORS_AND_TELEMETRY.md)).
- **Modos de vuelo inteligentes integrados** (seguimiento de sujeto, tomas automáticas, control por app / palm takeoff según lo documenta DJI en la página del producto). Estos modos son cerrados: los ejecuta el firmware, no son programables externamente.
- **Registro de vuelos**: DJI Fly almacena logs de vuelo (práctica estándar del ecosistema DJI; el detalle exacto de campos por modelo debe verificarse en los logs reales — ver [EXPERIMENTS_TODO.md](EXPERIMENTS_TODO.md)).
- **DJI Fly como app de control oficial** y DJI Assistant 2 como herramienta de mantenimiento/actualización.

Referencias: página oficial del producto, soporte y descargas — ver [SOURCES.md](SOURCES.md).

## 🔧 Técnicamente inferido

- **El vídeo de la cámara principal puede extraerse hacia un PC** por alguna vía (streaming desde DJI Fly, captura de pantalla del móvil, RTMP si el firmware/app lo habilita para este modelo, o post-proceso de grabaciones). La vía concreta y su latencia deben validarse experimentalmente — es el **Experimento 1** del proyecto.
- **Existe un canal de comunicación bidireccional Neo ↔ DJI Fly** (vídeo + estados básicos como batería y avisos), puesto que la app los muestra. Que exista internamente **no** implica que sea accesible para terceros.

## 🧪 Experimental (por demostrar)

- Streaming RTMP en vivo desde DJI Fly con el Neo específicamente (DJI ofrece RTMP personalizado en *productos compatibles*; hay que confirmar si el Neo está entre ellos con la versión actual de DJI Fly).
- Extracción de telemetría útil (pose, altitud, actitud) desde los logs de vuelo de DJI Fly en post-proceso.
- Latencia y calidad del vídeo suficientes para SLAM en tiempo real vs. mapeo offline.

## ❌ No disponible (no asumir)

- SDK oficial (Mobile SDK V5 no lista al Neo como aeronave soportada).
- API pública de telemetría en vivo, control programático o acceso a sensores crudos.

Ver detalle completo en [DJI_NEO_LIMITATIONS.md](DJI_NEO_LIMITATIONS.md).

## Rol del Neo en el proyecto

Dado lo anterior, el DJI Neo se trata como:

- ✅ **Sensor volador**: fuente de vídeo RGB para percepción, SLAM y mapeo (pilotado manualmente).
- ❌ **NO** como plataforma de navegación autónoma programable — al menos hasta que un experimento demuestre lo contrario.

Toda la arquitectura del sistema debe mantenerse **desacoplada del Neo** mediante un `drone-control adapter` modular (ver [AUTONOMOUS_NAVIGATION_CHALLENGES.md](AUTONOMOUS_NAVIGATION_CHALLENGES.md)).
