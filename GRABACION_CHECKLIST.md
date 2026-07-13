# Checklist de grabación — primera toma (el cuarto)

Objetivo de esta toma: **un vídeo de 1–3 minutos del cuarto** que un SLAM visual pueda procesar. No busques una toma bonita; busca una toma *útil*.

## Antes de despegar

- [ ] **Mide el cuarto con cinta métrica.** Largo × ancho × alto. Apúntalo en `data/raw/README.md`. Sin esto el mapa no tiene escala real.
- [ ] **Deja un objeto de tamaño conocido a la vista** (una caja, una regla, una hoja tamaño carta pegada a la pared). Anota sus medidas.
- [ ] **Enciende la luz.** Cierra la cortina si entra sol directo: los cambios de exposición rompen el tracking.
- [ ] **Ordena un poco:** el SLAM necesita textura. Muebles, libreros, pósters, cables y esquinas son buenos. Una pared blanca lisa es un agujero negro.
- [ ] Si DJI Fly lo permite, **desactiva la estabilización electrónica** (RockSteady / HorizonBalancing). 🔧 Deforma la imagen y rompe el modelo de cámara. Si no se puede, no pasa nada — lo probamos igual.
- [ ] Calidad: **1080p a 60 fps** es mejor que 4K a 30. Más fotogramas ayudan al tracking más que más píxeles.
- [ ] Batería llena. Vuelo manual con DJI Fly (no modos automáticos).

## Durante el vuelo

- [ ] **Empieza trasladándote de lado**, despacio, un par de metros, mirando hacia una pared con cosas. **No gires sobre tu eje al principio.** ← el error #1
- [ ] Movimientos **lentos y suaves**. El desenfoque de movimiento destruye las features.
- [ ] Recorre el cuarto en bucle, encuadrando zonas con textura. Evita llenar el cuadro con pared vacía.
- [ ] Giros amplios y lentos, nunca bruscos.
- [ ] **Cierra el bucle:** termina volviendo al punto y encuadre exactos de inicio. Permite que el SLAM se reconozca y corrija la deriva.

## Después

- [ ] Aterriza. Conecta **el dron** (no el mando) por USB-C al PC.
- [ ] Copia el `.mp4` **tal cual, sin recomprimir ni editar** a `data/raw/`.
- [ ] Nómbralo `cuarto_01.mp4` (siguiente intento: `cuarto_02_lento.mp4`, etc.).
- [ ] Rellena la fila en la tabla de `data/raw/README.md`: iluminación, notas de vuelo, medidas del cuarto.

## Opcional pero muy útil (para la calibración de cámara, Experimento E3)

- [ ] Imprime un **patrón de tablero de ajedrez** (chessboard) y grábalo 30–60 s con el dron, moviéndolo para que el tablero aparezca en distintas posiciones, ángulos y distancias del encuadre. Guárdalo como `calib_01.mp4`.
- [ ] Sin esto habrá que autocalibrar, que da peores resultados.

## Recordatorio de por qué

El SLAM monocular estima la posición de la cámara triangulando puntos vistos desde **dos posiciones distintas**. Si solo giras, todos los rayos salen del mismo punto: no hay triangulación posible y el sistema nunca inicializa. Traslación + textura + luz constante = mapa. Rotación + pared blanca = nada.
