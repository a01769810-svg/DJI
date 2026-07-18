# Mediciones del cuarto — ground truth métrico (para fijar la ESCALA del mapa SLAM)

El SLAM monocular reconstruye la geometría **en unidades arbitrarias**: sabe las *proporciones*
pero no el *tamaño real*. Para que "avanza 50 cm" signifique algo, necesitamos **distancias
reales conocidas** de objetos rígidos que salgan claros en el vídeo. Rellena los campos y me
los pasas (edita este archivo o dímelos en el chat).

## Cómo medir (leer antes)
- **Todo en milímetros (mm).** Usa cinta métrica metálica, no flexómetro de tela.
- **Mide el borde que se VE en el vídeo** (ver notas por objeto). Anota qué borde usaste si dudas.
- **Mide dos veces** cada cosa; si no coinciden, apunta las dos.
- Marca con `?` cualquier dato inseguro. Es mejor un `?` que un número inventado.
- Las paredes de tu cuarto son casi todo blanco liso (mal para SLAM): **estos objetos con
  textura son a la vez la referencia de escala Y los puntos que el SLAM va a seguir.** Por eso
  medimos justo estos.

---

## A. Referencias principales (rígidas + con textura)

Diagrama de una PUERTA (mide la **HOJA**, el panel que se mueve; el "vano" es el hueco del marco):
```
   +-----------------+   <- borde SUPERIOR de la hoja
   |                 |
   |      HOJA       |  alto = de borde superior a borde inferior de la hoja
   |            [o]  |  <- manija
   |                 |
   +-----------------+   <- borde INFERIOR
   |<--- ancho ----->|
```

### A1. Puerta de ENTRADA (la principal)
- Alto de la hoja (mm): _____2100_____
- Ancho de la hoja (mm): _____888_____
- (opcional) Alto del vano/marco por dentro (mm): __________
- (opcional) Ancho del vano por dentro (mm): __________
- Altura del piso al borde INFERIOR de la hoja (mm, 0 si llega al piso): ______0____
- ¿En qué pared está? / notas: _____en la misma pared que las medallas_____

### A2. Segunda puerta (¿clóset? ¿baño? — dime cuál)
- ¿Qué puerta es?: ____Del baño y closet______
- Alto de la hoja (mm): ______2100____
- Ancho de la hoja (mm): _________707_
- Altura del piso al borde inferior (mm): ____0______
- Pared / notas: ____es menos ancha que la principal______

### A3. Televisión  (mide el rectángulo EXTERIOR del bisel/marco negro — es la arista de alto
    contraste contra la pared blanca; la diagonal en pulgadas es solo respaldo)
- Ancho exterior (bisel incluido) (mm): _______1115___
- Alto exterior (bisel incluido) (mm): ______640____
- (respaldo) Diagonal nominal (pulgadas): _______no entendi___
- Altura del piso al borde INFERIOR de la tele (mm): ________1077__
- Pared / notas: _____esta mirando hacia la cama_____

### A4. Marco de las medallas  (mide el borde EXTERIOR del marco)
- Ancho exterior (mm): ________495__
- Alto exterior (mm): ________604__
- Altura del piso al borde inferior (mm): _____1342_____
- Pared / notas: ______esta en la misma pared que las dos puertas____

---

## B. Geometría del cuarto (para CRUZAR la escala y no depender de un solo objeto)

### B1. Altura del cuarto (suelo → techo)
- Punto 1 (mm): _____3240_____
- Punto 2, en otra esquina (mm): _____3240_____   ← si no coinciden, el techo no es plano; útil saberlo

### B2. Pared más larga y despejada
- ¿Cuál pared? (p. ej. "la de la tele"): ___Tele_______
- Largo esquina a esquina (mm): _______4440___

### B3. Pared perpendicular a la anterior
- Largo esquina a esquina (mm): _____3330_____

*(Con B2 + B3 tenemos el "footprint" aproximado del cuarto.)*

---

## C. (Opcional pero muy útil) Distancias entre objetos fijos
Una o dos distancias horizontales entre cosas que NO se mueven sirven de chequeo extra:
- Distancia horizontal entre ____tele______ y ___cama_______ (mm): __850________
- Distancia horizontal entre _____limite derecho de puerta principal_____ y ____limite izquierdo de puerta de baño y closet______ (mm): ___930_______

---

## D. Croquis / notas de distribución
Dibuja (o descríbeme) una vista **desde arriba** del cuarto: qué pared tiene la tele, dónde
están las dos puertas, dónde el marco de medallas y el minisplit. No tiene que ser bonito —
me sirve para asociar cada medición con su lugar en el mapa.

```
(espacio para tu croquis / notas)

Si vieras el cuarto desde el centro hasta arriba apuntando hacia la puerta principal a tu izquierda te encontrarias con mi escritorio, y la tele la cual tiene una tipo repisa. Literalmente abajo tuya estaria mi cama, despues enfrente estan las puertas y las medallas, a tu derecha estaria el minisplit y el cuadro que dice santi y un lugar donde puse peluches y cosas; y por ultimo la ventana estaria atras tuya

```

---

### Recordatorio para el vuelo de mapeo (no es medición, pero cuenta)
Que la puerta de entrada, la tele y el marco de medallas salgan **claros, llenando buena parte
del cuadro y vistos con traslación** (moviéndote de lado, no solo de frente) — eso es lo que le
da profundidad (paralaje) al SLAM. Y dado lo blanco de las paredes, considera pegar 2-3 hojas
A4 (297×210 mm exactos) como textura extra; si lo haces, avísame y las añadimos como referencia.
