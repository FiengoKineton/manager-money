"""Windows-friendly local launcher for Money Manager.

The launcher creates a repository-local virtual environment, installs runtime
requirements only when needed, starts the Flask app from that environment, and
opens a local browser app window. When that browser app window is closed, the
server is stopped automatically.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Iterable, Sequence

APP_HOST = "127.0.0.1"
APP_PORT = 5000

STATE_FILE = ".launcher_state.json"
APP_CONFIG_DIR_NAME = "MoneyManagerLauncher"
APP_CONFIG_FILE_NAME = "config.json"
LEGACY_CONFIG_FILE = ".money_manager_launcher_config.json"
LEGACY_PATH_CACHE_FILE = ".money_manager_project_path.txt"
BROWSER_PROFILE_DIR = ".launcher_browser_profile"
DATA_HOME_ENV = "MONEY_MANAGER_DATA_HOME"
DATA_HOME_FOLDER_NAME = "MoneyManagerData"


def _app_url(host: str, port: int) -> str:
    return f"http://{host}:{port}"


def _port_is_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False


def _choose_available_port(host: str, preferred_port: int, *, search_count: int = 40) -> int:
    if not _port_is_open(host, preferred_port):
        return preferred_port
    for port in range(preferred_port + 1, preferred_port + search_count + 1):
        if not _port_is_open(host, port):
            print(f"Port {preferred_port} is already in use. Using port {port} instead.")
            return port
    print(f"Ports {preferred_port}-{preferred_port + search_count} are busy.")
    print("Close old Money Manager/Python windows from Task Manager, then try again.")
    raise SystemExit(1)


def _launcher_log_path(data_home: Path) -> Path:
    logs_dir = data_home / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir / "launcher_latest.log"


def _print_log_tail(path: Path, *, lines: int = 80) -> None:
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return
    tail = content[-lines:]
    if not tail:
        return
    print("")
    print(f"Last {len(tail)} launcher/server log lines from: {path}")
    print("-" * 72)
    for line in tail:
        print(line)
    print("-" * 72)


def _launcher_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _user_config_dir() -> Path:
    """Return the per-user launcher config directory.

    On Windows this is usually:
    C:\\Users\\<user>\\AppData\\Local\\MoneyManagerLauncher

    Keeping this outside the .bat folder prevents copied Desktop launchers from
    creating visible helper files next to the icon.
    """
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / APP_CONFIG_DIR_NAME

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_CONFIG_DIR_NAME

    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home) / APP_CONFIG_DIR_NAME
    return Path.home() / ".config" / APP_CONFIG_DIR_NAME


def _config_path() -> Path:
    return _user_config_dir() / APP_CONFIG_FILE_NAME


def _legacy_config_paths() -> list[Path]:
    launch_dir = _launcher_dir()
    return [
        launch_dir / LEGACY_CONFIG_FILE,
        launch_dir / LEGACY_PATH_CACHE_FILE,
    ]


def _is_project_dir(path: Path) -> bool:
    return (
        path.is_dir()
        and (path / "money_manager" / "app.py").is_file()
        and (path / "requirements.txt").is_file()
        and (path / "run_money_manager.py").is_file()
    )


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True)
    try:
        path.write_text(text, encoding="utf-8")
    except PermissionError:
        # The remembered launcher config is optional.
        # Do not block startup if AppData is protected.
        pass


def _update_launcher_config(**values) -> dict:
    path = _config_path()
    payload = _read_json(path)
    payload.update({key: str(value) for key, value in values.items() if value is not None})
    try:
        _write_json(path, payload)
    except Exception:
        pass
    return payload

def _candidate_project_dirs(config_path: Path) -> list[Path]:
    candidates: list[Path] = []

    env_dir = os.environ.get("MONEY_MANAGER_PROJECT_DIR")
    if env_dir:
        candidates.append(Path(env_dir).expanduser())

    config = _read_json(config_path)
    if config.get("project_dir"):
        candidates.append(Path(config["project_dir"]).expanduser())

    # Backward compatibility with launchers generated before the config moved
    # to AppData. These are read only; new writes go to _config_path().
    for legacy_path in _legacy_config_paths():
        if not legacy_path.exists():
            continue
        if legacy_path.name == LEGACY_CONFIG_FILE:
            legacy_config = _read_json(legacy_path)
            if legacy_config.get("project_dir"):
                candidates.append(Path(legacy_config["project_dir"]).expanduser())
        elif legacy_path.name == LEGACY_PATH_CACHE_FILE:
            try:
                cached_path = legacy_path.read_text(encoding="utf-8").strip().strip('"')
            except Exception:
                cached_path = ""
            if cached_path:
                candidates.append(Path(cached_path).expanduser())

    launch_dir = _launcher_dir()
    candidates.extend([Path.cwd(), launch_dir, launch_dir.parent])

    for parent in launch_dir.parents:
        candidates.append(parent)

    # De-duplicate while preserving order.
    unique: list[Path] = []
    seen: set[str] = set()
    for item in candidates:
        try:
            resolved = item.resolve()
        except Exception:
            resolved = item
        key = str(resolved).lower() if os.name == "nt" else str(resolved)
        if key not in seen:
            seen.add(key)
            unique.append(resolved)
    return unique


def _ask_for_project_dir(config_path: Path) -> Path:
    print("Money Manager project folder was not found automatically.")
    print("Select the folder that contains money_manager/, data/, requirements.txt, and run_money_manager.py.")
    print(f"The selected path will be remembered in: {config_path}")

    while True:
        raw = input("Project folder path: ").strip().strip('"')
        if not raw:
            continue
        candidate = Path(raw).expanduser().resolve()
        if _is_project_dir(candidate):
            _update_launcher_config(project_dir=candidate)
            return candidate
        print("That folder does not look like the Money Manager repo. Try again.")


def find_project_dir() -> Path:
    config_path = _config_path()
    for candidate in _candidate_project_dirs(config_path):
        if _is_project_dir(candidate):
            # Store the path for future runs, useful when the launcher becomes an .exe
            # or when a copied/renamed .bat is moved outside the repo.
            try:
                _update_launcher_config(project_dir=candidate)
            except Exception:
                pass
            return candidate
    return _ask_for_project_dir(config_path)


def project_dir_from_arg(raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser().resolve()
    if not _is_project_dir(candidate):
        print(f"Invalid project folder: {candidate}")
        print("Expected a folder containing money_manager/app.py, requirements.txt, and run_money_manager.py.")
        raise SystemExit(1)

    try:
        _update_launcher_config(project_dir=candidate)
    except Exception:
        pass

    return candidate


def _resolve_data_home(project_dir: Path, requested: str | None = None) -> Path:
    if requested:
        return Path(requested).expanduser().resolve()
    env_home = os.environ.get(DATA_HOME_ENV)
    if env_home:
        return Path(env_home).expanduser().resolve()
    config = _read_json(_config_path())
    if config.get("data_home"):
        return Path(str(config["data_home"])).expanduser().resolve()
    return (project_dir / DATA_HOME_FOLDER_NAME).resolve()


def _warn_about_data_home(project_dir: Path, data_home: Path) -> None:
    """Make accidental use of a second device-local data copy visible.

    The launcher intentionally supports custom/external data folders, so it must
    not silently rewrite that choice.  It should, however, clearly say when a
    Git pull of the project cannot update the folder currently used for money
    data.
    """
    expected = (project_dir / DATA_HOME_FOLDER_NAME).resolve()
    active = data_home.resolve()
    if active == expected:
        return
    print("")
    print("WARNING: Money Manager is using a custom data folder:")
    print(f"  active:  {active}")
    print(f"  project: {expected}")
    print("Pulling the code repository does not necessarily update the active data folder.")
    if (expected / "data" / "users").exists():
        print("A second MoneyManagerData folder also exists inside the project. Check 'Why this net?' before editing data.")
    print("")


def ensure_data_home(project_dir: Path, data_home: Path) -> None:
    for folder in (
        data_home / "app_config",
        data_home / "data" / "_system",
        data_home / "data" / "users",
        data_home / "backups",
        data_home / "updates" / "inbox",
        data_home / "updates" / "staging",
        data_home / "updates" / "installed",
        data_home / "updates" / "failed",
        data_home / "updates" / "rollback",
        data_home / "logs",
        data_home / "cache",
    ):
        folder.mkdir(parents=True, exist_ok=True)
    try:
        _update_launcher_config(project_dir=project_dir, data_home=data_home)
    except Exception:
        pass

    env = os.environ.copy()
    env[DATA_HOME_ENV] = str(data_home)
    command = find_base_python() + [
        "-c",
        "from money_manager.config.app_home import ensure_app_home; ensure_app_home()",
    ]
    result = _run_capture(command, cwd=project_dir, env=env)
    if result.returncode != 0:
        print(result.stdout)
        print("Data folder configuration could not be initialized.")
        raise SystemExit(result.returncode)


def apply_staged_updates_before_start(project_dir: Path, data_home: Path) -> None:
    tool = project_dir / "tools" / "apply_update.py"
    if not tool.exists():
        return
    env = os.environ.copy()
    env[DATA_HOME_ENV] = str(data_home)
    result = _run_capture(find_base_python() + [str(tool)], cwd=project_dir, env=env)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.returncode != 0:
        print("A staged update failed. The launcher will continue with the current code if rollback succeeded.")


def _run_capture(command: Sequence[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(command),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        **kwargs,
    )


def _python_command_candidates() -> list[list[str]]:
    candidates: list[list[str]] = []
    if not getattr(sys, "frozen", False):
        candidates.append([sys.executable])
    if os.name == "nt":
        candidates.append(["py", "-3"])
    candidates.extend([["python"], ["python3"]])
    return candidates


def find_base_python() -> list[str]:
    for command in _python_command_candidates():
        try:
            result = _run_capture(command + ["-c", "import sys; print(sys.executable)"])
        except FileNotFoundError:
            continue
        if result.returncode == 0:
            return command

    print("Python was not found.")
    print("Install Python 3.10 or newer from python.org, and enable 'Add python.exe to PATH'.")
    print("After installing Python, run launcher.bat again.")
    raise SystemExit(1)


def _venv_python(project_dir: Path) -> Path:
    if os.name == "nt":
        return project_dir / ".venv" / "Scripts" / "python.exe"
    return project_dir / ".venv" / "bin" / "python"


def _requirements_hash(requirements_path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(requirements_path.read_bytes())
    return digest.hexdigest()


def _ensure_pip(venv_python: Path) -> None:
    result = _run_capture([str(venv_python), "-m", "pip", "--version"])
    if result.returncode == 0:
        return

    print("pip is missing inside the virtual environment; trying ensurepip...")
    ensurepip = _run_capture([str(venv_python), "-m", "ensurepip", "--upgrade"])
    if ensurepip.returncode != 0:
        print(ensurepip.stdout)
        print("pip could not be installed in the virtual environment.")
        raise SystemExit(1)


def _state_says_requirements_installed(state_path: Path, requirements_hash: str, venv_python: Path) -> bool:
    state = _read_json(state_path)
    return (
        state.get("requirements_hash") == requirements_hash
        and state.get("venv_python") == str(venv_python)
        and state.get("install_ok") is True
    )


def ensure_environment(project_dir: Path) -> Path:
    requirements_path = project_dir / "requirements.txt"
    state_path = project_dir / STATE_FILE
    venv_dir = project_dir / ".venv"
    venv_python = _venv_python(project_dir)

    base_python = find_base_python()

    if not venv_python.exists():
        print("Creating local virtual environment in .venv ...")
        result = subprocess.run(base_python + ["-m", "venv", str(venv_dir)], cwd=project_dir)
        if result.returncode != 0:
            print("Could not create .venv. Check that your Python installation includes the venv module.")
            raise SystemExit(result.returncode)

    _ensure_pip(venv_python)

    req_hash = _requirements_hash(requirements_path)
    if _state_says_requirements_installed(state_path, req_hash, venv_python):
        print("Virtual environment is up to date.")
        return venv_python

    print("Installing project requirements into .venv ...")
    install = subprocess.run(
        [str(venv_python), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(requirements_path)],
        cwd=project_dir,
    )
    if install.returncode != 0:
        print("Dependency installation failed. No global Python packages were changed.")
        raise SystemExit(install.returncode)

    _write_json(
        state_path,
        {
            "install_ok": True,
            "requirements_hash": req_hash,
            "venv_python": str(venv_python),
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
    )
    return venv_python


def _wait_for_server(host: str, port: int, process: subprocess.Popen, timeout_seconds: float = 45.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with socket.create_connection((host, port), timeout=0.4):
                return True
        except OSError:
            time.sleep(0.35)
    return process.poll() is None


def _browser_candidates() -> list[Path]:
    """Return browser executables that support app-window mode."""
    names = ["msedge", "chrome", "chrome.exe", "msedge.exe"] if os.name == "nt" else [
        "microsoft-edge",
        "google-chrome",
        "chromium",
        "chromium-browser",
    ]

    candidates: list[Path] = []
    for name in names:
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))

    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        program_files = os.environ.get("PROGRAMFILES", "")
        program_files_x86 = os.environ.get("PROGRAMFILES(X86)", "")
        candidates.extend(
            Path(base) / rel
            for base in [program_files, program_files_x86, local_app_data]
            if base
            for rel in [
                r"Microsoft\Edge\Application\msedge.exe",
                r"Google\Chrome\Application\chrome.exe",
            ]
        )
    elif sys.platform == "darwin":
        candidates.extend(
            [
                Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
                Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
            ]
        )

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            resolved = candidate
        key = str(resolved).lower() if os.name == "nt" else str(resolved)
        if key not in seen and resolved.exists():
            seen.add(key)
            unique.append(resolved)
    return unique


def _open_managed_browser_window(project_dir: Path, url: str) -> subprocess.Popen | None:
    """Open a separate app-style browser window we can monitor reliably.

    Opening the default browser is easy, but detecting when the user closes only
    that app tab/window is not reliable. A Chromium/Edge app window with a
    repo-local user profile gives this launcher a concrete process to wait on.
    """
    browsers = _browser_candidates()
    if not browsers:
        return None

    browser = browsers[0]
    profile_dir = project_dir / BROWSER_PROFILE_DIR
    profile_dir.mkdir(exist_ok=True)

    command = [
        str(browser),
        f"--app={url}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--disable-default-apps",
    ]
    try:
        return subprocess.Popen(command, cwd=project_dir)
    except Exception as exc:
        print(f"Could not open managed browser window with {browser}: {exc}")
        return None


def _open_default_browser(url: str) -> None:
    try:
        webbrowser.open(url)
    except Exception:
        print(f"Open this URL manually: {url}")


def _stop_process(process: subprocess.Popen | None, label: str) -> int:
    if process is None:
        return 0
    if process.poll() is not None:
        return int(process.returncode or 0)

    print(f"Stopping {label}...")
    process.terminate()
    try:
        return int(process.wait(timeout=8) or 0)
    except subprocess.TimeoutExpired:
        process.kill()
        return int(process.wait() or 0)


def _wait_until_browser_closes(server_process: subprocess.Popen, browser_process: subprocess.Popen | None) -> int:
    if browser_process is None:
        print("Browser opened. Close this terminal window or press Ctrl+C to stop the server.")
        return server_process.wait()

    print("Browser opened in app mode. Close the browser window to stop Money Manager automatically.")
    while True:
        server_status = server_process.poll()
        if server_status is not None:
            return int(server_status or 0)

        browser_status = browser_process.poll()
        if browser_status is not None:
            print("Browser window closed. Stopping Money Manager automatically...")
            _stop_process(server_process, "Money Manager server")
            return 0

        time.sleep(0.5)


def start_app(
    project_dir: Path,
    venv_python: Path,
    *,
    data_home: Path,
    use_default_browser: bool = False,
    preferred_port: int = APP_PORT,
) -> int:
    port = _choose_available_port(APP_HOST, preferred_port)
    url = _app_url(APP_HOST, port)
    command = [
        str(venv_python),
        str(project_dir / "run_money_manager.py"),
        "--host",
        APP_HOST,
        "--port",
        str(port),
        "--no-browser",
    ]

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env[DATA_HOME_ENV] = str(data_home)

    log_path = _launcher_log_path(data_home)
    log_handle = log_path.open("a", encoding="utf-8", errors="replace")
    log_handle.write("\n" + "=" * 80 + "\n")
    log_handle.write(time.strftime("%Y-%m-%d %H:%M:%S") + " starting Money Manager\n")
    log_handle.write(f"project_dir={project_dir}\n")
    log_handle.write(f"data_home={data_home}\n")
    log_handle.write(f"command={' '.join(command)}\n")
    log_handle.flush()

    print(f"Starting Money Manager at {url}")
    print(f"Server log: {log_path}")
    server_process = subprocess.Popen(
        command,
        cwd=project_dir,
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )

    try:
        if not _wait_for_server(APP_HOST, port, server_process):
            try:
                server_process.wait(timeout=2)
            except Exception:
                pass
            log_handle.flush()
            print("The server stopped before it was ready.")
            _print_log_tail(log_path)
            return int(server_process.returncode or 1)

        browser_process = None
        if not use_default_browser:
            browser_process = _open_managed_browser_window(project_dir, url)

        if browser_process is None:
            _open_default_browser(url)
            if not use_default_browser:
                print(
                    "Could not find Edge/Chrome app mode. The server cannot reliably auto-stop "
                    "when a normal browser tab is closed."
                )

        try:
            return _wait_until_browser_closes(server_process, browser_process)
        except KeyboardInterrupt:
            print("Stopping Money Manager...")
            _stop_process(browser_process, "browser window")
            return _stop_process(server_process, "Money Manager server")
    finally:
        try:
            log_handle.flush()
            log_handle.close()
        except Exception:
            pass


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start Money Manager with a local desktop launcher.")
    parser.add_argument(
        "--project-dir",
        help="Project folder resolved by launcher.bat. If valid, no folder prompt is shown.",
    )
    parser.add_argument(
        "--data-home",
        help="External MoneyManagerData folder. Defaults to a sibling folder next to the app code.",
    )
    parser.add_argument(
        "--default-browser",
        action="store_true",
        help="Open the normal default browser instead of a managed app window. Auto-stop on browser close is disabled.",
    )
    parser.add_argument(
        "--port",
        default=APP_PORT,
        type=int,
        help=f"Preferred local port. Default: {APP_PORT}. If busy, the launcher will pick the next free port.",
    )
    parser.add_argument(
        "--foreground",
        action="store_true",
        help="Accepted for launcher.bat compatibility; run behavior is unchanged inside launcher.py.",
    )
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.project_dir:
        project_dir = project_dir_from_arg(args.project_dir)
    else:
        project_dir = find_project_dir()

    data_home = _resolve_data_home(project_dir, args.data_home)
    _warn_about_data_home(project_dir, data_home)
    ensure_data_home(project_dir, data_home)
    print(f"Using project folder: {project_dir}")
    print(f"Using data folder: {data_home}")

    apply_staged_updates_before_start(project_dir, data_home)
    venv_python = ensure_environment(project_dir)
    return start_app(
        project_dir,
        venv_python,
        data_home=data_home,
        use_default_browser=args.default_browser,
        preferred_port=int(args.port or APP_PORT),
    )


if __name__ == "__main__":
    raise SystemExit(main())
