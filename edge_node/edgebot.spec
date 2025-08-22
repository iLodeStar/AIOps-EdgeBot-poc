# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

# Analysis configuration
a = Analysis(
    ['cli.py'],
    pathex=['./'],
    binaries=[],
    datas=[
        ('config.example.yaml', '.'),  # Include example config
    ],
    hiddenimports=[
        'app.config',
        'app.inputs.syslog_server',
        'app.inputs.snmp_poll', 
        'app.inputs.weather',
        'app.inputs.file_tailer',
        'app.inputs.flows_listener',
        'app.inputs.nmea_listener',
        'app.inputs.service_discovery',
        'app.output.shipper',
        'uvloop',
        'structlog',
        'httpx',
        'aiofiles',
        'pysnmp',
        'prometheus_client',
        'aiohttp',
        'geoip2',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tests',
        'test_*',
        'pytest',
        'unittest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
# Remove test modules and unnecessary files
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='edgebot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,  # Strip symbols for smaller size
    upx=False,   # Don't use UPX compression to avoid compatibility issues
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
