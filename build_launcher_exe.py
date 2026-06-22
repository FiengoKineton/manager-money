"""Build helper for a future standalone launcher executable.

This does not build or include an executable unless you run it manually.
The launcher stores its remembered project path in the user AppData config,
so the future .exe can be moved without creating helper files on the Desktop.
It requires PyInstaller in your current Python environment:
    python -m pip install pyinstaller
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    project_dir = Path(__file__).resolve().parent
    launcher = project_dir / "launcher.py"
    if not launcher.exists():
        print("launcher.py was not found next to this script.")
        return 1

    try:
        import PyInstaller.__main__  # noqa: F401
    except ImportError:
        print("PyInstaller is not installed in this Python environment.")
        print("Run: python -m pip install pyinstaller")
        return 1

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--name",
        "MoneyManagerLauncher",
        "--clean",
        "--distpath",
        str(project_dir / "dist"),
        "--workpath",
        str(project_dir / "build"),
        str(launcher),
    ]
    print("Running:")
    print(" ".join(command))
    return subprocess.call(command, cwd=project_dir)


if __name__ == "__main__":
    raise SystemExit(main())
