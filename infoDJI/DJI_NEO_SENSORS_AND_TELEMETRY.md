# DJI Neo — Sensores y telemetría

## Sensores inferiores

### ✅ Confirmado oficialmente

El DJI Neo incorpora **sistemas inferiores de posicionamiento**, que incluyen:

- **Visión inferior** (cámara orientada hacia abajo) para estabilización y posicionamiento.
- **Detección infrarroja** (sensado de distancia hacia abajo) usada para mantenimiento de altura y aterrizaje.

Referencia principal: manual oficial del DJI Neo, disponible en la página de descargas — https://www.dji.com/neo/downloads (usar el manual como fuente canónica de especificaciones de sensores).

### ❌ No disponible: acceso externo a esos sensores

**No existe documentación pública oficial** que permita obtener en una aplicación propia:

- frames crudos de la cámara inferior;
- distancia cruda del sensor infrarrojo;
- lecturas individuales de sensores;
- point cloud del sensor inferior.

> **Importante:** que el dron utilice internamente un sensor NO significa que exista una API pública para acceder a sus valores. Los sensores inferiores del Neo son, a efectos de este proyecto, una caja negra que mejora la estabilidad del vuelo manual — nada más.

## Telemetría

### ✅ Confirmado

- DJI Fly muestra en pantalla estados del dron durante el vuelo (batería, avisos, etc.) y almacena registros de vuelo.

### 🔧 Técnicamente inferido

- Existe un protocolo interno Neo ↔ DJI Fly que transporta vídeo y estados. Su existencia se infiere del comportamiento de la app; su contenido y formato **no** están documentados públicamente.

### 🧪 Experimental — vías de investigación (sin garantías)

Posibles líneas de investigación para obtener telemetría, todas por demostrar:

1. **Logs de vuelo de DJI Fly** (post-proceso, no en vivo): exportar los registros y analizar qué campos contienen para el Neo (posición relativa, altitud, actitud, batería…). Es la vía más prometedora y menos invasiva, pero sirve solo para análisis *a posteriori*, p. ej. contrastar trayectorias con la salida del SLAM.
2. **Análisis del tráfico entre Neo y DJI Fly**: inspección de protocolos de enlace. Complejidad alta, posible cifrado, frágil ante actualizaciones.
3. **DJI Assistant 2**: revisar qué datos expone para el Neo (normalmente orientado a firmware/calibración, no a telemetría en vivo).
4. **Proyectos open-source de la comunidad** sobre protocolos DJI: evaluar si alguno cubre la generación de hardware del Neo. Verificar licencias, estado de mantenimiento y aplicabilidad real antes de depender de ellos.

### ❌ No asumir hasta demostrarlo experimentalmente

- Que se podrá controlar completamente el Neo.
- Que se podrá acceder al sensor infrarrojo.
- Que se podrá obtener la cámara inferior.
- Que se podrá conseguir telemetría en vivo.

## Implicación para la arquitectura

Como no hay telemetría oficial, la **pose del dron debe estimarse externamente** a partir del vídeo de la cámara principal (SLAM visual / VIO / localización visual). La telemetría de logs, si resulta útil, se usará solo como validación offline — nunca como dependencia del pipeline principal.

Ver pipeline completo en [HOUSE_MAPPING_ARCHITECTURE.md](HOUSE_MAPPING_ARCHITECTURE.md) y experimentos en [EXPERIMENTS_TODO.md](EXPERIMENTS_TODO.md).
