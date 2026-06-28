[app]

# (str) Title of your application
title = Voice Assistant

# (str) Package name
package.name = voiceassistant

# (str) Package domain (needed for android packaging)
package.domain = org.assistant

# (str) Source code directory
source.dir = .

# (list) Source files to include (let empty to include all the files)
source.include_exts = py,png,jpg,kv,atlas,json

# (list) List of exclusions using pattern matching
#source.exclude_patterns = license,images/*wav

# (str) Application versioning (method 1)
version = 1.0.0

# (list) Application requirements
# comma separated e.g. requirements = sqlite3,kivy
requirements = python3,kivy,speechrecognition,plyer,requests,urllib3,certifi,idna,charset_normalizer,pyjnius

# (str) Custom source folders for requirements
# It may be useful when some source folders are needed for compile
#requirements.source.kivy = ../../kivy

# (list) Garden requirements
#garden_requirements =

# (str) Presplash of the application
#presplash.filename = %(source.dir)s/data/presplash.png

# (str) Icon of the application
#icon.filename = %(source.dir)s/data/icon.png

# (str) Supported orientations (one of landscape, sensorLandscape, portrait or all)
orientation = portrait

# (list) List of service to declare
#services = voice_service:./services/voice_service.py:foreground

#
# Android specific
#

# (bool) Indicate if the XML export should be used
#android.xml_export = True

# (list) Permissions
android.permissions = RECORD_AUDIO, INTERNET, FOREGROUND_SERVICE

# (int) Target Android API, should be as high as possible.
android.api = 33

# (int) Minimum API your APK will support.
android.minapi = 21

# (str) Android NDK version to use
#android.ndk = 25b

# (bool) Use --private data directory (True, default) or --dir public directory (False)
#android.private_storage = True

# (str) Android NDK directory (if empty, it will be automatically downloaded)
#android.ndk_path =

# (str) Android SDK directory (if empty, it will be automatically downloaded)
#android.sdk_path =

# (str) ANT directory (if empty, it will be automatically downloaded)
#android.ant_path =

# (str) Java directory (if empty, it will be automatically downloaded)
#android.jack_path =

# (list) Android architectures to build for, choices: armeabi-v7a, arm64-v8a, x86, x86_64
android.archs = arm64-v8a, armeabi-v7a

# (bool) Allow service to be ran in foreground
android.foreground_service = true

# (list) The Android libraries to add (as a string or a list of maven artifacts)
#android.dependencies =

# (str) Android logcat filters to use
android.logcat_filters = *:S python:D VoiceAssistant:D

# (bool) Copy library instead of linking (useful for windows tools path issue)
#android.copy_libs = 1

# (str) The theme to use (default will be used if not set)
#android.theme = @android:style/Theme.NoTitleBar

[buildozer]

# (int) Log level (0 = error only, 1 = info, 2 = debug (with command output))
log_level = 2

# (int) Display warning if buildozer is run as root (0 = false, 1 = true)
warn_on_root = 1

# (str) Path to buildozer run directory
#buildozer_dir = .buildozer
