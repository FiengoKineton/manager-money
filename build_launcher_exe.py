"""Build optional Windows launcher executables with project branding.

Run this on Windows after installing PyInstaller. The normal build is windowed
(no console); the diagnostic build keeps a console. Both remain portable because
launcher.py resolves/asks for the repository and stores its path in AppData.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _build(project_dir: Path, *, name: str, windowed: bool) -> int:
    launcher = project_dir / "launcher.py"
    icon = project_dir / "static" / "icons" / "money-manager.ico"
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--clean",
        "--name",
        name,
        "--icon",
        str(icon),
        "--distpath",
        str(project_dir / "dist"),
        "--workpath",
        str(project_dir / "build" / name),
    ]
    command.append("--windowed" if windowed else "--console")
    command.append(str(launcher))
    print("Running:")
    print(" ".join(command))
    return subprocess.call(command, cwd=project_dir)


def main() -> int:
    project_dir = Path(__file__).resolve().parent
    if not (project_dir / "launcher.py").exists():
        print("launcher.py was not found next to this script.")
        return 1
    if not (project_dir / "static" / "icons" / "money-manager.ico").exists():
        print("static/icons/money-manager.ico was not found.")
        return 1
    try:
        import PyInstaller.__main__  # noqa: F401
    except ImportError:
        print("PyInstaller is not installed. Run: python -m pip install pyinstaller")
        return 1

    normal = _build(project_dir, name="MoneyManagerLauncher", windowed=True)
    if normal != 0:
        return normal
    return _build(project_dir, name="MoneyManagerConsole", windowed=False)


if __name__ == "__main__":
    raise SystemExit(main())
