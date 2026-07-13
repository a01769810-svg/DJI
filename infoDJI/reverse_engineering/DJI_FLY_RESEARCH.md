# Investigación de DJI Fly (app `dji.go.v5`)

> DJI Fly es el único software oficial que controla el Neo, y confirmadamente lo pilota por WiFi con joysticks virtuales. Por tanto **la cadena joystick→serialización→transporte→dron vive dentro del APK**. Si el tráfico en el cable resultara cifrado, recuperar esa cadena del propio código es la vía alternativa (independiente del cifrado del transporte).

## Datos base

- **`[CONFIRMED]`** Package name: **`dji.go.v5`** (no `com.dji.fly`). Mismo linaje de código que DJI GO 4 (`com.dji.industry.pilot` para Pilot). → apkpure/apkcombo.
- **`[CONFIRMED]`** El Neo se pilota con **joysticks virtuales por WiFi sin mando** (stick izq = altitud/orientación, der = traslación); también Palm/Voice Control. → soporte DJI 01700011389.

## La barrera: SecNeo (packer)

- **`[CONFIRMED]`** DJI Fly está empaquetada con **SecNeo**: un wrapper `com.secneo` carga **`libDexHelper.so`**, que descifra los `.dex` en memoria en runtime (RC4, clave derivada de XOR de constante hardcodeada con el nombre del package). Ofuscación por aplanamiento de flujo, cifrado de strings, y **anti-debugging + detección específica de Frida**. → Abrir el APK con JADX/apktool "a secas" **no** revela el código de control.
- **`[CONFIRMED]`** También presente **`libwaes.so`** (whitebox AES para claves de No-Fly-Zones), roto por Synacktiv con análisis de fallos diferenciales.
- **`[CONFIRMED]` (GO 4)** Strings cifrados con XOR de clave única reutilizada `b"Y*IBg^Yd"` → descifrado automatizable tras decompilar. Transferibilidad exacta a la versión actual de DJI Fly: `[medium]` (la clave/esquema pudo cambiar).

## La metodología (ya resuelta por terceros)

- **`[EXPERIMENTAL]`** Synacktiv, Quarkslab y RECON'23 **ya** desempaquetaron apps DJI hermanas: volcaron los **7-8 dex descifrados de memoria con Frida/gdb** (las herramientas de unpacking tradicionales fallan) y los recompusieron con **dex2jar** antes de decompilar con JADX. El packer engancha ART (`Instrumentation::InitializeMethodsCode`) para restaurar bytecode ofuscado en verificación de clases. Requiere dispositivo/emulador rooteado y bypass de detección Frida.
- **`[UNKNOWN]`** **Ninguna publicación aísla la tabla de comandos de vuelo del Neo** ni identifica referencias internas al "Neo" en el APK decompilado. La metodología y las barreras están resueltas; falta el trabajo dirigido al Neo. (Nota: `libnc.so` no se confirmó como componente de DJI Fly; las `.so` verificadas son `libDexHelper.so` y `libwaes.so`.)

## Plan de análisis (cadena joystick → dron)

Objetivo: seguir `evento joystick UI → representación de control → serialización → transporte → dron`.

1. **Estático (E-OBS-5):** descargar `dji.go.v5`, listar `.so` con apktool, confirmar `com.secneo`/`libDexHelper.so`, cargar `libDexHelper.so` en Ghidra para entender el descifrado RC4.
2. **Dinámico (Frida, tras E-OBS-5):** en dispositivo/emulador root con bypass anti-Frida, hookear `libDexHelper.so`, volcar los dex, `dex2jar` + JADX.
3. **Localizar la frontera Java→nativo:** `grep` de `System.load`/`native` y términos `stick`/`joystick`/`virtual`; usar **jadx-native-libraries-plugin** para mapear métodos JNI de las `.so` a Java; Ghidra para el nivel CPU.
4. **Banco de pruebas:** una vez conocido el cmd_set/cmd_id/payload de vuelo del Neo, reenviar con `pyduml`/`DUMLFlasher`/`B3YOND`.

## Herramientas

JADX/jadx-gui · apktool · Frida/gdb · dex2jar · Ghidra/IDA · jadx-native-libraries-plugin · Wireshark + dissectors DUML · script de descifrado XOR de strings · `pyduml`/`DUMLFlasher` (banco de pruebas).

**Fuentes clave:** Quarkslab "DJI: The Art of Obfuscation"; Synacktiv "DJI Android GO 4 security analysis"; slides RECON'23 (mschloegel.me); `o-gs/dji-firmware-tools`; `andyjsmith/jadx-native-libraries-plugin`; `xaionaro/reverse-engineering-dji`. Lista completa en [`SOURCES.md`](SOURCES.md).
