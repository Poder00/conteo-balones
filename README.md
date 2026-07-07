# Conteo de Balones de GLP — App por Turno

App Android nativa (Kivy + OpenCV) para conteo automatico de llenados de
balones de gas, con control de apertura y cierre de turno.

## Que hace la app

1. **Apertura de turno**: el operador ingresa su nombre. Se registra la hora.
2. **Referencia**: enfoca el area vacia, define el recuadro (ROI) arrastrando
   el dedo, y captura la imagen de referencia.
3. **Conteo automatico**: al presionar COMENZAR, el celular (en su soporte)
   detecta cada llenado comparando el area contra la referencia. Maquina de
   estados: VACIA -> CONFIRMANDO -> LLENANDO -> conteo +1.
4. **Cierre de turno**: el operador que cierra ingresa su nombre. Se muestra
   un resumen (operador apertura/cierre, horas, total). Se guarda en CSV+JSON.

Los reportes quedan guardados en el celular (carpeta `conteo_balones_data`)
en dos formatos: un JSON por turno y un `reporte_turnos.csv` acumulado.

---

## COMO COMPILAR EL APK (sin Android Studio)

No necesitas instalar nada pesado. GitHub compila el APK por ti en la nube.

### Paso 1 — Crear cuenta en GitHub
Si no tienes, registrate gratis en https://github.com

### Paso 2 — Crear un repositorio nuevo
1. Click en el boton **New** (o "+") arriba a la derecha.
2. Ponle un nombre, por ejemplo `conteo-balones`.
3. Dejalo en **Public** (o Private, da igual para compilar).
4. Click en **Create repository**.

### Paso 3 — Subir estos archivos
La forma mas facil sin comandos:
1. En tu repo nuevo, click en **uploading an existing file**.
2. Arrastra TODOS los archivos de este proyecto:
   - `main.py`
   - `buildozer.spec`
   - `README.md`
   - `.gitignore`
   - la carpeta `.github` completa (con `workflows/build.yml` dentro)

   > IMPORTANTE: la carpeta `.github/workflows/` debe subirse tal cual.
   > Si arrastrando no te deja subir carpetas, usa GitHub Desktop
   > (https://desktop.github.com) que es visual y sencillo.
3. Abajo, click en **Commit changes**.

### Paso 4 — Esperar la compilacion
1. Ve a la pestana **Actions** de tu repo.
2. Veras un job llamado "Compilar APK" corriendo (punto amarillo).
3. La PRIMERA vez tarda ~20-30 min (descarga el SDK de Android y OpenCV).
   Las siguientes son mas rapidas.
4. Cuando termine, el punto se pone verde.

### Paso 5 — Descargar el APK
1. Click en el job que termino (verde).
2. Baja hasta la seccion **Artifacts**.
3. Descarga `conteo-balones-apk`. Es un .zip; adentro esta el `.apk`.

### Paso 6 — Instalar en el celular
1. Pasa el .apk al celular (WhatsApp, cable, Drive...).
2. Abrelo. Android pedira permitir "instalar de fuentes desconocidas": acepta.
3. Al abrir la app, acepta los permisos de camara y almacenamiento.

---

## Ajustes de calibracion

En `main.py`, arriba, estan los parametros. Los mas importantes:

- `T_MINIMO_LLENADO_S = 15.0` — tiempo minimo de un llenado real. Ajustalo al
  ~70% del ciclo real mas rapido (igual que en tu sistema Python original).
- `PORCENTAJE_OCUPACION = 0.25` — cuanto del area debe cambiar para contar
  como "ocupada". Subelo si cuenta de mas, bajalo si no detecta.
- `UMBRAL_DIFERENCIA = 40` — sensibilidad al cambio de imagen (0-255).

Tras cambiar valores, vuelve a subir `main.py` al repo y GitHub recompila solo.

---

## Notas tecnicas

- Compilado para `arm64-v8a` (cubre casi todos los celulares desde ~2017).
- Si tu celular es muy viejo y no instala, agrega `armeabi-v7a` en
  `buildozer.spec` (linea `android.archs`).
- La deteccion depende de luz estable. Si la iluminacion del area cambia mucho
  durante el turno, puede afectar el conteo (limitacion de la comparacion por
  diferencia de imagen, no de esta app en particular).
