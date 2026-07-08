# -*- mode: python ; coding: utf-8 -*-
# RapidOCR 専用ビルド設定（自分用・DirectML GPU）
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []

# RapidOCR 本体 + 同梱 onnx モデル・yaml 設定を丸ごと取り込む
for pkg in ('rapidocr', 'onnxruntime'):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # 使わない重量級エンジンを除外してサイズ削減
    excludes=[
        'paddleocr', 'paddle', 'paddlex',
        'easyocr', 'torch', 'torchvision', 'torchaudio',
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='kindle-ocr',
    console=True,       # コンソールウィンドウを表示してログ(print)を出す
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name='kindle-ocr',   # dist/kindle-ocr/ フォルダに出力
)
