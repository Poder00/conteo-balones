[app]

title = Detector Balones
package.name = detectorbalones
package.domain = com.gas
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
version = 2.0

# Dependencias: solo kivy + numpy (compilan bien, sin opencv ni pillow)
requirements = python3,kivy,numpy

orientation = portrait
fullscreen = 0

android.permissions = CAMERA,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE

android.api = 31
android.minapi = 24
android.archs = arm64-v8a
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 0
