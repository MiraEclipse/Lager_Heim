# PyInstaller-Spezifikation der PC-Version (LagerHeim.exe)
from PyInstaller.utils.hooks import collect_submodules

a = Analysis(
    ["lager_heim_pc.py"],
    datas=[("app/static", "app/static"), ("app/schema.sql", "app")],
    hiddenimports=collect_submodules("uvicorn"),
    excludes=["tkinter", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas,
    name="LagerHeim",
    console=False,
    upx=False,
)
