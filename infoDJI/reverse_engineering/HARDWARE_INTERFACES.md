# Hardware e interfaces de debug

> Foco: silicio del Neo, radios, y si existe alguna interfaz física (UART/JTAG/USB) que ayude a observar el sistema. Vía **invasiva y de alto riesgo** — se **aplaza** hasta agotar las rutas de software.

## Identidad y radios

- **`[CONFIRMED]`** FCC ID **`SS3-DN1A062624`** (grantee SS3 = SZ DJI; modelo interno tipo DN1A). Expediente público con fotos internas/externas, manual y reportes RF por banda. El Neo 2 tiene un FCC ID separado (`SS3-DEP125`).
- **`[CONFIRMED]`** La radio principal **hacia el teléfono es WiFi estándar de doble banda + BLE** (reportes FCC: 2.4G WiFi, NII-WiFi 5.17-5.23 GHz, SRD 5.73-5.84 GHz, BLE, SRD). **No** hay reporte "OcuSync". Coincide con el AP WiFi P2P para DJI Fly.
- **`[CONFIRMED]`** Doble modo de transmisión: además del WiFi, el Neo usa el enlace propietario **O4 (OcuSync 4)** con RC-N3/RC 2/Goggles N3/Motion Controller (hasta 10 km FCC, 1080p/60, ~31 ms). Parte del espectro 5.8 GHz de los reportes SRD podría corresponder a O4 (sin confirmar cuál reporte).
- **`[OBSERVED]`** Dos antenas WiFi 2×2 MIMO serigrafiadas `ZTX-WA521-(L/R-A)-V2` + una antena GNSS separada (cable coaxial). ("ZTX-WA521" = nomenclatura de la pieza de antena, no un chipset — pero nótese la coincidencia con el código de modelo `wa521`.)
- **`[CONFIRMED]`** Puerto **USB-C con pines de datos** en la placa principal (sostiene el flujo offline y es la superficie DUML más accesible).
- **`[CONFIRMED]`** Receptor **GNSS** a bordo (antena confirmada), aunque sin API oficial de telemetría → la pose sigue teniendo que estimarse por visión externa en interiores.

## Silicio (lo que NO se sabe)

- **`[UNKNOWN]`** El **SoC principal** (visión/aplicaciones) y el **MCU de control de vuelo** no están identificados públicamente: en las fotos FCC están bajo **blindajes RF con pasta térmica azul, sin marcas legibles**. Ni el reporte FCC, ni iFixit, ni blogs/foros transcriben marcas de chips.
- **`[INFERRED, medium]`** El enlace O4 casi con seguridad usa el ASIC OcuSync **"Sparrow 2" (S2)** de DJI (mismo de Mini 4 Pro y Avata 2, cohorte 2024). Los ASICs OcuSync de DJI (P1 "Pigeon", S1/S2 "Sparrow") son de diseño propio, derivados de la arquitectura Leadcore LC1860 → el módem RF en O4 **no** es un chip WiFi comercial (Realtek/Broadcom).
- **`[UNKNOWN]`** RAM y almacenamiento (~22 GB, sin microSD) sin part number público; probablemente bajo el mismo blindaje.

## Interfaces de debug (candidatas, sin mapear)

- **`[CONFIRMED]`** Los módulos internos de los drones DJI se comunican por **UART** (y algo de I2C) con DUML; existe tooling (dji-firmware-tools) para sniffar DUML y extraer firmware por ese vector.
- **`[UNKNOWN]`** **No hay documentación pública de UART TX/RX, JTAG, SWD o test pads mapeados en el PCB del Neo concreto.** Históricamente los DJI exponen test pads UART `[INFERRED transferibilidad]`, pero contraejemplo útil: Neodyme **no** halló UART/JTAG en el Potensic Atom 2. La búsqueda no siempre tiene éxito.

## Procedimiento (APLAZADO — solo tras agotar software)

1. Teardown guiado por iFixit; fotografiar PCB a alta resolución.
2. Retirar blindajes con cuidado; identificar SoC/eMMC por part number.
3. Buscar y sondear posibles test pads UART (3V3/GND/TX/RX) con analizador lógico, probar 115200 baud.
4. Como último recurso (muy invasivo): extracción física de NAND (desoldar + lector SPI) — técnica probada en otros drones.

> ⚠️ **No** realizar modificaciones físicas destructivas sin detenerse antes, explicarlo y obtener aprobación explícita. Abrir el dron implica riesgo físico y pérdida de garantía.

**Fuentes clave:** `fcc.report/FCC-ID/SS3-DN1A062624` (expediente + fotos internas `7505295.pdf`); `fccid.io/SS3-DN1A062624`; iFixit teardown del Neo; fpvwiki (linaje ASICs OcuSync); `o-gs/dji-firmware-tools`; Neodyme "drone hacking part 1". Lista completa en [`SOURCES.md`](SOURCES.md).
