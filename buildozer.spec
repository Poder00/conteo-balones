[app]

title = Conteo Balones
package.name = conteobalones
package.domain = com.triton
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
version = 1.0

# Dependencias: SIN opencv. Solo kivy + numpy. Mucho mas probable que compile.
requirements = python3,kivy,numpy,pillow

orientation = portrait
fullscreen = 0

# Permisos: camara + almacenamiento
android.permissions = CAMERA,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE

android.api = 31
android.minapi = 24
android.archs = arm64-v8a
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 0
