# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['desktop_pet.py'],
    pathex=[],
    binaries=[],
    datas=[('assets/smooth','assets/smooth'), ('assets/voices','assets/voices'), ('assets/cat.ico','assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
# Qt 6.12 uses Windows' ICU API. A Poppler directory in the build host's
# PATH contains a different ICU ABI; never bundle that unrelated library.
a.binaries = [e for e in a.binaries if e[0].lower() not in ('icuuc.dll', 'icudt78.dll')]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='CatDesktopPet',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets/cat.ico'],
)
