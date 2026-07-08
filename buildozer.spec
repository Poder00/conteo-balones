[app]

title = Detector Balones
package.name = detectorbalones
package.domain = com.gas
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
version = 3.1

requirements = python3,kivy,numpy

orientation = portrait
fullscreen = 0

android.permissions = CAMERA,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE

android.archs = arm64-v8a
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 0
