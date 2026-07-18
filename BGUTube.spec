import os
from pathlib import Path

block_cipher = None

# Locate Playwright's Chromium from the developer's local install
playwright_base = Path(os.environ['LOCALAPPDATA']) / 'ms-playwright'
chromium_dirs = list(playwright_base.glob('chromium*'))
if not chromium_dirs:
    raise RuntimeError(
        "Chromium not found in %LOCALAPPDATA%\\ms-playwright\\ — "
        "run: playwright install chromium"
    )

datas = [('Media/Logo.png', 'Media')]
for chromium_dir in chromium_dirs:
    datas.append((str(chromium_dir), f'ms-playwright/{chromium_dir.name}'))

a = Analysis(
    ['src/UI.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'playwright',
        'playwright.async_api',
        'playwright._impl._api_types',
        'playwright._impl._browser_type',
        'playwright._impl._connection',
        'playwright._impl._playwright',
        'playwright._impl._network',
        'playwright._impl._page',
        'greenlet',
        'httpx',
        'httpx._transports.default',
        'PIL._tkinter_finder',
    ],
    hookspath=['build_hooks'],
    runtime_hooks=['build_hooks/playwright_env.py'],
    excludes=['Media.LoginInfo'],  # gitignored dev credentials — must never ship in the exe
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='BGUTube',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
