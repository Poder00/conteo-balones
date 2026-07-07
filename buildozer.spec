[app]

# Nombre visible de la app
title = Conteo Balones

# Nombre del paquete (sin espacios, minusculas)
package.name = conteobalones

# Dominio (invertido). Puedes dejar este o poner el tuyo.
package.domain = com.triton

# Carpeta con el codigo fuente
source.dir = .

# Extensiones de archivo a incluir
source.include_exts = py,png,jpg,kv,atlas

# Version de la app
version = 1.0

# Dependencias de Python. IMPORTANTE: opencv y numpy para el conteo.
requirements = python3,kivy==2.3.0,numpy,opencv,pyjnius,android

# Orientacion de pantalla
orientation = portrait

# Pantalla completa (0 = no, 1 = si)
fullscreen = 0

# --- Permisos de Android ---
android.permissions = CAMERA,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE,INTERNET

# API objetivo y minima de Android
android.api = 31
android.minapi = 24

# Arquitecturas a compilar (arm64 cubre casi todos los celulares modernos)
android.archs = arm64-v8a

# Aceptar automaticamente las licencias del SDK
android.accept_sdk_license = True

# Icono (opcional). Si agregas un icon.png en la carpeta, descomenta:
# icon.filename = %(source.dir)s/icon.png

[buildozer]

# Nivel de log (2 = detallado, util para depurar)
log_level = 2

# No advertir si se corre como root (necesario en CI)
warn_on_root = 0
