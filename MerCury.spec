# -*- mode: python ; coding: utf-8 -*-
import sys
import os
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# Hidden imports needed for dynamic loading
hidden_imports = [
    'engineio.async_drivers.threading',
    'sqlalchemy.dialects.sqlite',
    'alembic',
    'mercury.data.models',  # Ensure models are found
    # pywebview dependencies
    'webview',
    'bottle',
    'proxy_tools',
]

# Exclude uvloop on Windows (implicit, generally PyInstaller handles it, but safe to list if needed)
excludes = []
if sys.platform == 'win32':
    excludes.append('uvloop')

# Define datas
my_datas = [
    ('src/mercury/web/templates', 'mercury/web/templates'),
]
if os.path.exists('src/mercury/web/static'):
    my_datas.append(('src/mercury/web/static', 'mercury/web/static'))

a = Analysis(
    ['src/mercury/autostart.py'],
    pathex=[],
    binaries=[],
    datas=my_datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# Filter out None from datas if static didn't exist
# a.datas = [d for d in a.datas if d is not None]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MerCury',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='MerCury',
)

app = BUNDLE(
    coll,
    name='MerCury.app',
    icon=None,
    bundle_identifier='com.mercury.app',
)
