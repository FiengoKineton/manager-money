"""Portable desktop launcher for the local Money Manager web application.

Normal Windows startup is performed by ``MoneyManager.vbs`` with ``pythonw``.
The launcher keeps all device-specific state under the user's application-data
folder, prepares the virtual environment, starts the local server without a
console, opens Edge/Chrome in app mode, and supervises restart/shutdown.
"""
from __future__ import annotations

import argparse
import contextlib
import ctypes
import hashlib
import json
import os
import queue
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

APP_NAME = "Money Manager"
APP_HOST = "127.0.0.1"
APP_PORT = 5000
APP_TITLE_TOKEN = "Money Manager"
APP_CONFIG_DIR_NAME = "MoneyManagerLauncher"
APP_CONFIG_FILE_NAME = "config.json"
RUNTIME_STATE_FILE_NAME = "runtime.json"
BOOTSTRAP_LOG_FILE_NAME = "launcher_bootstrap.log"
LEGACY_CONFIG_FILE = ".money_manager_launcher_config.json"
LEGACY_PATH_CACHE_FILE = ".money_manager_project_path.txt"
LEGACY_STATE_FILE = ".launcher_state.json"
DATA_HOME_ENV = "MONEY_MANAGER_DATA_HOME"
DATA_HOME_FOLDER_NAME = "MoneyManagerData"
MUTEX_NAME = r"Local\MoneyManagerDesktopLauncher"
CONTROL_MAX_BYTES = 16 * 1024

_HIDDEN_MODE = False
_BOOTSTRAP_LOG_HANDLE = None
_MUTEX_HANDLE = None


@dataclass
class ManagedServer:
    process: subprocess.Popen
    log_handle: object
    log_path: Path
    host: str
    port: int
    url: str
    instance_id: str


@dataclass
class ManagedBrowser:
    process: subprocess.Popen | None
    executable: Path | None
    name: str
    root_pid: int
    hwnd: int = 0


def _app_url(host: str, port: int) -> str:
    browser_host = "127.0.0.1" if host in {"0.0.0.0", "::", ""} else host
    return f"http://{browser_host}:{port}"


def _launcher_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _user_config_dir() -> Path:
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


def _runtime_state_path() -> Path:
    return _user_config_dir() / RUNTIME_STATE_FILE_NAME


def _browser_profile_dir(project_dir: Path) -> Path:
    suffix = hashlib.sha256(str(project_dir.resolve()).encode("utf-8", errors="replace")).hexdigest()[:12]
    return _user_config_dir() / f"browser-profile-{suffix}"


def _environment_state_path(project_dir: Path) -> Path:
    suffix = hashlib.sha256(str(project_dir.resolve()).encode("utf-8", errors="replace")).hexdigest()[:12]
    return _user_config_dir() / f"environment-{suffix}.json"


def _launcher_log_path(data_home: Path) -> Path:
    logs_dir = data_home / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir / "launcher_latest.log"


def _read_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    text = json.dumps(payload, indent=2, sort_keys=True)
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _safe_write_json(path: Path, payload: dict) -> None:
    try:
        _write_json(path, payload)
    except Exception:
        pass


def _update_launcher_config(**values) -> dict:
    path = _config_path()
    payload = _read_json(path)
    payload.update({key: str(value) for key, value in values.items() if value is not None})
    _safe_write_json(path, payload)
    return payload


def _runtime_payload(**values) -> dict:
    payload = _read_json(_runtime_state_path())
    payload.update(values)
    payload["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    return payload


def _write_runtime_state(**values) -> dict:
    payload = _runtime_payload(**values)
    _safe_write_json(_runtime_state_path(), payload)
    return payload


def _clear_runtime_state() -> None:
    try:
        _runtime_state_path().unlink(missing_ok=True)
    except Exception:
        pass


def _prepare_output(hidden: bool) -> None:
    global _HIDDEN_MODE, _BOOTSTRAP_LOG_HANDLE
    _HIDDEN_MODE = bool(hidden)
    if not hidden:
        return
    config_dir = _user_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    log_path = config_dir / BOOTSTRAP_LOG_FILE_NAME
    handle = log_path.open("a", encoding="utf-8", errors="replace", buffering=1)
    handle.write("\n" + "=" * 80 + "\n")
    handle.write(time.strftime("%Y-%m-%d %H:%M:%S") + " hidden launcher start\n")
    _BOOTSTRAP_LOG_HANDLE = handle
    sys.stdout = handle
    sys.stderr = handle


def _close_output() -> None:
    global _BOOTSTRAP_LOG_HANDLE
    handle = _BOOTSTRAP_LOG_HANDLE
    _BOOTSTRAP_LOG_HANDLE = None
    if handle is not None:
        try:
            handle.flush()
            handle.close()
        except Exception:
            pass


def _show_message(title: str, message: str, *, error: bool = False) -> None:
    if os.name == "nt":
        try:
            flags = 0x00000010 if error else 0x00000040  # MB_ICONERROR / MB_ICONINFORMATION
            ctypes.windll.user32.MessageBoxW(None, str(message), str(title), flags)
            return
        except Exception:
            pass
    print(f"{title}: {message}")


def _fatal_message(message: str, *, log_path: Path | None = None) -> None:
    details = [str(message).strip()]
    if log_path:
        details.extend(["", f"Log: {log_path}"])
    details.extend(["", "Run MoneyManagerConsole.bat for visible diagnostic output."])
    _show_message(f"{APP_NAME} launcher error", "\n".join(details), error=True)


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


def _subprocess_windows_options(*, hidden: bool | None = None, new_process_group: bool = False) -> dict:
    options: dict = {}
    if os.name != "nt":
        return options
    should_hide = _HIDDEN_MODE if hidden is None else bool(hidden)
    creationflags = 0
    if should_hide:
        creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0  # SW_HIDE
        options["startupinfo"] = startupinfo
    if new_process_group:
        creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    if creationflags:
        options["creationflags"] = creationflags
    return options


def _run_capture(command: Sequence[str], **kwargs) -> subprocess.CompletedProcess:
    options = _subprocess_windows_options()
    options.update(kwargs)
    return subprocess.run(
        list(command),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        **options,
    )


def _is_project_dir(path: Path) -> bool:
    return (
        path.is_dir()
        and (path / "launcher.py").is_file()
        and (path / "money_manager" / "app.py").is_file()
        and (path / "requirements.txt").is_file()
        and (path / "run_money_manager.py").is_file()
    )


def _legacy_config_paths() -> list[Path]:
    launch_dir = _launcher_dir()
    return [launch_dir / LEGACY_CONFIG_FILE, launch_dir / LEGACY_PATH_CACHE_FILE]


def _candidate_project_dirs(config_path: Path) -> list[Path]:
    candidates: list[Path] = []
    env_dir = os.environ.get("MONEY_MANAGER_PROJECT_DIR")
    if env_dir:
        candidates.append(Path(env_dir).expanduser())

    config = _read_json(config_path)
    if config.get("project_dir"):
        candidates.append(Path(str(config["project_dir"])).expanduser())

    for legacy_path in _legacy_config_paths():
        if not legacy_path.exists():
            continue
        if legacy_path.name == LEGACY_CONFIG_FILE:
            legacy_config = _read_json(legacy_path)
            if legacy_config.get("project_dir"):
                candidates.append(Path(str(legacy_config["project_dir"])).expanduser())
        else:
            try:
                raw = legacy_path.read_text(encoding="utf-8").strip().strip('"')
            except Exception:
                raw = ""
            if raw:
                candidates.append(Path(raw).expanduser())

    launch_dir = _launcher_dir()
    candidates.extend([Path.cwd(), launch_dir, launch_dir.parent])
    candidates.extend(launch_dir.parents)

    unique: list[Path] = []
    seen: set[str] = set()
    for item in candidates:
        try:
            resolved = item.resolve()
        except Exception:
            resolved = item
        key = str(resolved).casefold() if os.name == "nt" else str(resolved)
        if key not in seen:
            seen.add(key)
            unique.append(resolved)
    return unique


def _ask_for_project_dir(config_path: Path) -> Path:
    if _HIDDEN_MODE:
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            while True:
                chosen = filedialog.askdirectory(
                    title="Select the Money Manager project folder",
                    mustexist=True,
                    parent=root,
                )
                if not chosen:
                    root.destroy()
                    raise SystemExit(1)
                candidate = Path(chosen).expanduser().resolve()
                if _is_project_dir(candidate):
                    root.destroy()
                    _update_launcher_config(project_dir=candidate)
                    return candidate
                _show_message(
                    APP_NAME,
                    "The selected folder is not a valid Money Manager repository.\n\n"
                    "Select the folder containing launcher.py, run_money_manager.py, requirements.txt, and money_manager\\app.py.",
                    error=True,
                )
        except SystemExit:
            raise
        except Exception as exc:
            raise RuntimeError(f"The project folder could not be selected: {exc}") from exc

    print("Money Manager project folder was not found automatically.")
    print("Select the folder containing launcher.py, money_manager/, requirements.txt, and run_money_manager.py.")
    print(f"The selected path will be remembered in: {config_path}")
    while True:
        raw = input("Project folder path: ").strip().strip('"')
        if not raw:
            continue
        candidate = Path(raw).expanduser().resolve()
        if _is_project_dir(candidate):
            _update_launcher_config(project_dir=candidate)
            return candidate
        print("That folder does not look like the Money Manager repository. Try again.")


def find_project_dir() -> Path:
    config_path = _config_path()
    for candidate in _candidate_project_dirs(config_path):
        if _is_project_dir(candidate):
            _update_launcher_config(project_dir=candidate)
            return candidate
    return _ask_for_project_dir(config_path)


def project_dir_from_arg(raw_path: str) -> Path:
    candidate = Path(str(raw_path).strip().strip('"')).expanduser().resolve()
    if not _is_project_dir(candidate):
        raise RuntimeError(
            f"Invalid project folder: {candidate}\n"
            "Expected launcher.py, money_manager/app.py, requirements.txt, and run_money_manager.py."
        )
    _update_launcher_config(project_dir=candidate)
    return candidate


def _resolve_data_home(project_dir: Path, requested: str | None = None) -> Path:
    if requested:
        return Path(str(requested).strip().strip('"')).expanduser().resolve()
    env_home = os.environ.get(DATA_HOME_ENV)
    if env_home:
        return Path(env_home).expanduser().resolve()
    config = _read_json(_config_path())
    if config.get("data_home"):
        return Path(str(config["data_home"])).expanduser().resolve()
    return (project_dir / DATA_HOME_FOLDER_NAME).resolve()


def _warn_about_data_home(project_dir: Path, data_home: Path) -> None:
    expected = (project_dir / DATA_HOME_FOLDER_NAME).resolve()
    active = data_home.resolve()
    if active == expected:
        return
    print("")
    print("WARNING: Money Manager is using a custom data folder:")
    print(f"  active:  {active}")
    print(f"  project: {expected}")
    print("Replacing or updating the code repository does not replace the active data folder.")
    if (expected / "data" / "users").exists():
        print("A second MoneyManagerData folder also exists inside the project.")
    print("")


def _python_command_candidates() -> list[list[str]]:
    candidates: list[list[str]] = []
    if not getattr(sys, "frozen", False) and sys.executable:
        candidates.append([sys.executable])
    if os.name == "nt":
        candidates.extend([["py", "-3"], ["python"]])
    else:
        candidates.extend([["python3"], ["python"]])
    return candidates


def find_base_python() -> list[str]:
    for command in _python_command_candidates():
        try:
            result = _run_capture(command + ["-c", "import sys; print(sys.executable)"])
        except FileNotFoundError:
            continue
        if result.returncode == 0:
            return command
    raise RuntimeError(
        "Python 3.10 or newer was not found. Install Python from python.org and enable the Python launcher/PATH option."
    )


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

    _update_launcher_config(project_dir=project_dir, data_home=data_home)
    env = os.environ.copy()
    env[DATA_HOME_ENV] = str(data_home)
    command = find_base_python() + [
        "-c",
        "from money_manager.config.app_home import ensure_app_home; ensure_app_home()",
    ]
    result = _run_capture(command, cwd=project_dir, env=env)
    if result.returncode != 0:
        print(result.stdout)
        raise RuntimeError("The existing MoneyManagerData folder could not be initialized.")


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
        print("A staged update failed. The launcher will continue if the update tool completed its rollback.")


def _venv_python(project_dir: Path, *, windowed: bool = False) -> Path:
    if os.name == "nt":
        name = "pythonw.exe" if windowed else "python.exe"
        candidate = project_dir / ".venv" / "Scripts" / name
        if windowed and not candidate.exists():
            candidate = project_dir / ".venv" / "Scripts" / "python.exe"
        return candidate
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
        raise RuntimeError("pip could not be installed in the virtual environment.")


def _state_says_requirements_installed(state_path: Path, requirements_hash: str, venv_python: Path) -> bool:
    state = _read_json(state_path)
    return (
        state.get("requirements_hash") == requirements_hash
        and state.get("venv_python") == str(venv_python)
        and state.get("install_ok") is True
    )


def _migrate_legacy_environment_state(project_dir: Path, state_path: Path) -> None:
    if state_path.exists():
        return
    legacy = project_dir / LEGACY_STATE_FILE
    payload = _read_json(legacy)
    if payload:
        _safe_write_json(state_path, payload)


def ensure_environment(project_dir: Path) -> Path:
    requirements_path = project_dir / "requirements.txt"
    state_path = _environment_state_path(project_dir)
    _migrate_legacy_environment_state(project_dir, state_path)
    venv_dir = project_dir / ".venv"
    venv_python = _venv_python(project_dir)
    base_python = find_base_python()

    if not venv_python.exists():
        print("Creating the local virtual environment in .venv ...")
        result = _run_capture(base_python + ["-m", "venv", str(venv_dir)], cwd=project_dir)
        if result.returncode != 0:
            print(result.stdout)
            raise RuntimeError("The .venv environment could not be created.")

    _ensure_pip(venv_python)
    req_hash = _requirements_hash(requirements_path)
    if _state_says_requirements_installed(state_path, req_hash, venv_python):
        print("Virtual environment is up to date.")
        return venv_python

    print("Installing project requirements into .venv ...")
    install = _run_capture(
        [str(venv_python), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(requirements_path)],
        cwd=project_dir,
    )
    if install.returncode != 0:
        print(install.stdout)
        raise RuntimeError("Dependency installation failed. No global Python packages were changed.")

    _safe_write_json(
        state_path,
        {
            "install_ok": True,
            "requirements_hash": req_hash,
            "venv_python": str(venv_python),
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
    )
    return venv_python


def _port_is_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.25):
            return True
    except OSError:
        return False


def _wait_for_port_release(host: str, port: int, timeout_seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _port_is_open(host, port):
            return True
        time.sleep(0.25)
    return not _port_is_open(host, port)


def _choose_available_port(host: str, preferred_port: int, *, search_count: int = 40) -> int:
    if not _port_is_open(host, preferred_port):
        return preferred_port
    for port in range(preferred_port + 1, preferred_port + search_count + 1):
        if not _port_is_open(host, port):
            print(f"Port {preferred_port} is in use. Using port {port} instead.")
            return port
    raise RuntimeError(f"Ports {preferred_port}-{preferred_port + search_count} are busy.")


def _http_probe(url: str, *, timeout: float = 1.0) -> tuple[bool, bytes]:
    try:
        request = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= int(response.status) < 500, response.read(64 * 1024)
    except urllib.error.HTTPError as exc:
        return 200 <= int(exc.code) < 500, exc.read(64 * 1024)
    except Exception:
        return False, b""


def _wait_for_server(session: ManagedServer, timeout_seconds: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    ready_url = f"{session.url}/system/ready"
    while time.monotonic() < deadline:
        if session.process.poll() is not None:
            return False
        ok, body = _http_probe(ready_url, timeout=0.8)
        if ok and session.instance_id.encode("utf-8") in body:
            # Also verify the root route and branding asset before opening app mode.
            root_ok, _ = _http_probe(f"{session.url}/", timeout=1.5)
            icon_ok, _ = _http_probe(f"{session.url}/static/icons/money-manager.svg", timeout=1.5)
            if root_ok and icon_ok:
                return True
        time.sleep(0.3)
    return False


class LauncherControlServer:
    def __init__(self) -> None:
        self.token = secrets.token_urlsafe(32)
        self.commands: queue.Queue[dict] = queue.Queue()
        self._stop = threading.Event()
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((APP_HOST, 0))
        self._socket.listen(4)
        self._socket.settimeout(0.5)
        self.port = int(self._socket.getsockname()[1])
        self._thread = threading.Thread(target=self._serve, name="money-manager-launcher-control", daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                connection, _address = self._socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with connection:
                connection.settimeout(2.0)
                chunks: list[bytes] = []
                total = 0
                try:
                    while total < CONTROL_MAX_BYTES:
                        chunk = connection.recv(min(4096, CONTROL_MAX_BYTES - total))
                        if not chunk:
                            break
                        chunks.append(chunk)
                        total += len(chunk)
                        if b"\n" in chunk:
                            break
                    raw = b"".join(chunks).split(b"\n", 1)[0]
                    payload = json.loads(raw.decode("utf-8")) if raw else {}
                    if not secrets.compare_digest(str(payload.get("token") or ""), self.token):
                        response = {"ok": False, "error": "unauthorized"}
                    elif payload.get("command") not in {"restart", "shutdown", "focus"}:
                        response = {"ok": False, "error": "unsupported command"}
                    else:
                        self.commands.put(dict(payload))
                        response = {"ok": True, "accepted": payload.get("command")}
                except Exception as exc:
                    response = {"ok": False, "error": str(exc)}
                try:
                    connection.sendall(json.dumps(response).encode("utf-8") + b"\n")
                except Exception:
                    pass

    def get(self, timeout: float = 0.25) -> dict | None:
        try:
            return self.commands.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        self._stop.set()
        try:
            self._socket.close()
        except Exception:
            pass


def _start_server(
    project_dir: Path,
    venv_python: Path,
    *,
    data_home: Path,
    host: str,
    port: int,
    control: LauncherControlServer,
) -> ManagedServer:
    url = _app_url(host, port)
    instance_id = secrets.token_hex(16)
    server_python = _venv_python(project_dir, windowed=_HIDDEN_MODE)
    if not server_python.exists():
        server_python = venv_python
    command = [
        str(server_python),
        str(project_dir / "run_money_manager.py"),
        "--host",
        host,
        "--port",
        str(port),
        "--no-browser",
    ]
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env[DATA_HOME_ENV] = str(data_home)
    env["MONEY_MANAGER_DESKTOP_LAUNCHER"] = "1"
    env["MONEY_MANAGER_LAUNCHER_CONTROL_HOST"] = APP_HOST
    env["MONEY_MANAGER_LAUNCHER_CONTROL_PORT"] = str(control.port)
    env["MONEY_MANAGER_LAUNCHER_CONTROL_TOKEN"] = control.token
    env["MONEY_MANAGER_SERVER_INSTANCE_ID"] = instance_id
    env["MONEY_MANAGER_SERVER_HOST"] = host
    env["MONEY_MANAGER_SERVER_PORT"] = str(port)

    log_path = _launcher_log_path(data_home)
    log_handle = log_path.open("a", encoding="utf-8", errors="replace", buffering=1)
    log_handle.write("\n" + "=" * 80 + "\n")
    log_handle.write(time.strftime("%Y-%m-%d %H:%M:%S") + " starting Money Manager server\n")
    log_handle.write(f"project_dir={project_dir}\n")
    log_handle.write(f"data_home={data_home}\n")
    log_handle.write(f"url={url}\n")
    log_handle.write(f"command={' '.join(command)}\n")

    print(f"Starting Money Manager at {url}")
    print(f"Server log: {log_path}")
    options = _subprocess_windows_options(new_process_group=True)
    process = subprocess.Popen(
        command,
        cwd=project_dir,
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        **options,
    )
    session = ManagedServer(
        process=process,
        log_handle=log_handle,
        log_path=log_path,
        host=host,
        port=port,
        url=url,
        instance_id=instance_id,
    )
    if not _wait_for_server(session):
        try:
            process.wait(timeout=1)
        except Exception:
            pass
        log_handle.flush()
        _print_log_tail(log_path)
        raise RuntimeError("The local server stopped or did not become ready before the timeout.")
    return session


def _send_internal_shutdown(session: ManagedServer, token: str, action: str) -> bool:
    request = urllib.request.Request(
        f"{session.url}/system/internal-shutdown",
        data=json.dumps({"action": action}).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-MoneyManager-Launcher-Token": token,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=3.0) as response:
            return 200 <= int(response.status) < 300
    except Exception:
        return False


def _stop_process(process: subprocess.Popen | None, *, timeout: float = 8.0) -> int:
    if process is None:
        return 0
    if process.poll() is not None:
        return int(process.returncode or 0)
    try:
        process.terminate()
    except Exception:
        pass
    try:
        return int(process.wait(timeout=timeout) or 0)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except Exception:
            pass
        try:
            return int(process.wait(timeout=3) or 0)
        except Exception:
            return 1


def _stop_server(session: ManagedServer | None, token: str, *, action: str) -> int:
    if session is None:
        return 0
    try:
        if session.process.poll() is None:
            _send_internal_shutdown(session, token, action)
            try:
                return int(session.process.wait(timeout=10) or 0)
            except subprocess.TimeoutExpired:
                return _stop_process(session.process)
        return int(session.process.returncode or 0)
    finally:
        try:
            session.log_handle.flush()
            session.log_handle.close()
        except Exception:
            pass


def _browser_candidates() -> list[tuple[str, Path]]:
    candidates: list[tuple[str, Path]] = []
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA", "")
        program_files = os.environ.get("PROGRAMFILES", "")
        program_files_x86 = os.environ.get("PROGRAMFILES(X86)", "")
        edge_paths = [
            Path(base) / r"Microsoft\Edge\Application\msedge.exe"
            for base in (program_files_x86, program_files, local)
            if base
        ]
        chrome_paths = [
            Path(base) / r"Google\Chrome\Application\chrome.exe"
            for base in (program_files, program_files_x86, local)
            if base
        ]
        candidates.extend(("Microsoft Edge", path) for path in edge_paths)
        found_edge = shutil.which("msedge.exe") or shutil.which("msedge")
        if found_edge:
            candidates.append(("Microsoft Edge", Path(found_edge)))
        candidates.extend(("Google Chrome", path) for path in chrome_paths)
        found_chrome = shutil.which("chrome.exe") or shutil.which("chrome")
        if found_chrome:
            candidates.append(("Google Chrome", Path(found_chrome)))
    elif sys.platform == "darwin":
        candidates.extend(
            [
                ("Microsoft Edge", Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")),
                ("Google Chrome", Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")),
            ]
        )
    else:
        for name, executable in (
            ("Microsoft Edge", "microsoft-edge"),
            ("Google Chrome", "google-chrome"),
            ("Chromium", "chromium"),
            ("Chromium", "chromium-browser"),
        ):
            found = shutil.which(executable)
            if found:
                candidates.append((name, Path(found)))

    unique: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for name, candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            resolved = candidate
        key = str(resolved).casefold() if os.name == "nt" else str(resolved)
        if key not in seen and resolved.is_file():
            seen.add(key)
            unique.append((name, resolved))
    return unique


def _open_managed_browser_window(project_dir: Path, url: str) -> ManagedBrowser | None:
    browsers = _browser_candidates()
    if not browsers:
        return None

    profile_root = _browser_profile_dir(project_dir)
    for name, browser in browsers:
        # Keep Edge and Chrome profiles separate so a failed Edge attempt cannot
        # leave Chromium state that interferes with the Chrome fallback.
        profile_name = "edge" if "edge" in name.casefold() else "chrome"
        profile_dir = profile_root / profile_name
        profile_dir.mkdir(parents=True, exist_ok=True)
        command = [
            str(browser),
            f"--app={url}",
            "--start-maximized",
            f"--user-data-dir={profile_dir}",
            "--profile-directory=Default",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-default-apps",
            "--disable-session-crashed-bubble",
        ]
        try:
            process = subprocess.Popen(
                command,
                cwd=project_dir,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **_subprocess_windows_options(),
            )
            managed = ManagedBrowser(
                process=process,
                executable=browser,
                name=name,
                root_pid=int(process.pid),
            )
            if os.name != "nt" or _focus_browser(managed, retry_seconds=12.0):
                return managed
            print(f"{name} started but no matching app window appeared; trying the next browser.")
            _stop_browser(managed)
        except Exception as exc:
            print(f"Could not open {name} app mode: {exc}")
    return None


def _open_default_browser(url: str) -> None:
    try:
        webbrowser.open(url, new=1, autoraise=True)
    except Exception:
        print(f"Open this URL manually: {url}")


def _process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        SYNCHRONIZE = 0x00100000
        WAIT_TIMEOUT = 0x00000102
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel32.WaitForSingleObject.restype = wintypes.DWORD
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid)
            if not handle:
                return False
            try:
                return int(kernel32.WaitForSingleObject(handle, 0)) == WAIT_TIMEOUT
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _windows_process_tree(root_pid: int) -> set[int]:
    if os.name != "nt" or root_pid <= 0:
        return {root_pid} if root_pid > 0 else set()
    from ctypes import wintypes

    TH32CS_SNAPPROCESS = 0x00000002
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or ctypes.cast(snapshot, ctypes.c_void_p).value == INVALID_HANDLE_VALUE:
        return {root_pid}
    parents: dict[int, int] = {}
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    try:
        success = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while success:
            parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            success = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)

    tree = {int(root_pid)}
    changed = True
    while changed:
        changed = False
        for pid, parent in parents.items():
            if parent in tree and pid not in tree:
                tree.add(pid)
                changed = True
    return tree


def _window_title(hwnd: int) -> str:
    if os.name != "nt" or not hwnd:
        return ""
    try:
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int
        length = int(user32.GetWindowTextLengthW(hwnd))
        buffer = ctypes.create_unicode_buffer(max(1, length + 1))
        user32.GetWindowTextW(hwnd, buffer, len(buffer))
        return buffer.value
    except Exception:
        return ""


def _find_browser_window(root_pid: int, *, timeout_seconds: float = 12.0) -> int:
    if os.name != "nt" or root_pid <= 0:
        return 0
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD

    deadline = time.monotonic() + timeout_seconds
    fallback_hwnd = 0
    while time.monotonic() < deadline:
        pids = _windows_process_tree(root_pid)
        matches: list[tuple[int, str]] = []

        @WNDENUMPROC
        def enum_callback(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if int(pid.value) in pids:
                title = _window_title(int(hwnd))
                matches.append((int(hwnd), title))
            return True

        try:
            user32.EnumWindows(enum_callback, 0)
        except Exception:
            return 0

        for hwnd, title in matches:
            if APP_TITLE_TOKEN.casefold() in title.casefold():
                return hwnd
        if matches:
            fallback_hwnd = matches[0][0]
        time.sleep(0.25)
    return fallback_hwnd


def _focus_window(hwnd: int) -> bool:
    if os.name != "nt" or not hwnd:
        return False
    try:
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsWindow.restype = wintypes.BOOL
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.GetForegroundWindow.argtypes = []
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
        user32.AttachThreadInput.restype = wintypes.BOOL
        user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
        user32.AllowSetForegroundWindow.restype = wintypes.BOOL
        user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.ShowWindow.restype = wintypes.BOOL
        user32.BringWindowToTop.argtypes = [wintypes.HWND]
        user32.BringWindowToTop.restype = wintypes.BOOL
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        user32.SetActiveWindow.argtypes = [wintypes.HWND]
        user32.SetActiveWindow.restype = wintypes.HWND
        user32.SetFocus.argtypes = [wintypes.HWND]
        user32.SetFocus.restype = wintypes.HWND
        kernel32.GetCurrentThreadId.argtypes = []
        kernel32.GetCurrentThreadId.restype = wintypes.DWORD

        if not user32.IsWindow(hwnd):
            return False
        SW_MAXIMIZE = 3
        current_thread = int(kernel32.GetCurrentThreadId())
        target_thread = int(user32.GetWindowThreadProcessId(hwnd, None))
        foreground = int(user32.GetForegroundWindow() or 0)
        foreground_thread = int(user32.GetWindowThreadProcessId(foreground, None)) if foreground else 0
        attached_target = bool(
            target_thread
            and target_thread != current_thread
            and user32.AttachThreadInput(current_thread, target_thread, True)
        )
        attached_foreground = bool(
            foreground_thread
            and foreground_thread not in {current_thread, target_thread}
            and user32.AttachThreadInput(current_thread, foreground_thread, True)
        )
        try:
            user32.AllowSetForegroundWindow(0xFFFFFFFF)
            user32.ShowWindow(hwnd, SW_MAXIMIZE)
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetActiveWindow(hwnd)
            user32.SetFocus(hwnd)
        finally:
            if attached_foreground:
                user32.AttachThreadInput(current_thread, foreground_thread, False)
            if attached_target:
                user32.AttachThreadInput(current_thread, target_thread, False)
        return bool(user32.IsWindowVisible(hwnd))
    except Exception as exc:
        print(f"Window focus was not available: {exc}")
        return False


def _focus_browser(browser: ManagedBrowser, *, retry_seconds: float = 12.0) -> bool:
    if os.name != "nt":
        return False
    hwnd = browser.hwnd
    if hwnd and _focus_window(hwnd):
        return True
    hwnd = _find_browser_window(browser.root_pid, timeout_seconds=retry_seconds)
    if not hwnd:
        return False
    browser.hwnd = hwnd
    return _focus_window(hwnd)


def _window_exists(hwnd: int) -> bool:
    if os.name != "nt" or not hwnd:
        return False
    try:
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsWindow.restype = wintypes.BOOL
        return bool(user32.IsWindow(hwnd))
    except Exception:
        return False


def _stop_browser(browser: ManagedBrowser | None) -> None:
    if browser is None:
        return
    if os.name == "nt" and browser.root_pid > 0 and _process_exists(browser.root_pid):
        try:
            _run_capture(["taskkill", "/PID", str(browser.root_pid), "/T", "/F"])
            return
        except Exception:
            pass
    _stop_process(browser.process)


def _acquire_single_instance() -> bool:
    global _MUTEX_HANDLE
    if os.name != "nt":
        state = _read_json(_runtime_state_path())
        if state and _process_exists(int(state.get("launcher_pid") or 0)):
            return False
        return True
    try:
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        ctypes.set_last_error(0)
        handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        if not handle:
            return True
        ERROR_ALREADY_EXISTS = 183
        already_exists = ctypes.get_last_error() == ERROR_ALREADY_EXISTS
        if already_exists:
            kernel32.CloseHandle(handle)
            return False
        _MUTEX_HANDLE = handle
        return True
    except Exception:
        return True


def _release_single_instance() -> None:
    global _MUTEX_HANDLE
    if os.name == "nt" and _MUTEX_HANDLE:
        try:
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
            kernel32.ReleaseMutex.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
            kernel32.ReleaseMutex(_MUTEX_HANDLE)
            kernel32.CloseHandle(_MUTEX_HANDLE)
        except Exception:
            pass
    _MUTEX_HANDLE = None


def _focus_existing_instance() -> bool:
    deadline = time.monotonic() + 8.0
    state: dict = {}
    while time.monotonic() < deadline:
        state = _read_json(_runtime_state_path())
        hwnd = int(state.get("browser_hwnd") or 0)
        if hwnd and _focus_window(hwnd):
            return True
        browser_pid = int(state.get("browser_pid") or 0)
        if browser_pid > 0:
            browser = ManagedBrowser(
                process=None,
                executable=Path(str(state.get("browser_executable"))) if state.get("browser_executable") else None,
                name=str(state.get("browser_name") or "browser"),
                root_pid=browser_pid,
            )
            if _focus_browser(browser, retry_seconds=1.0):
                _write_runtime_state(browser_hwnd=browser.hwnd)
                return True
        time.sleep(0.35)
    url = str(state.get("url") or "")
    if url:
        ok, _ = _http_probe(f"{url}/system/ready", timeout=1.0)
        if ok:
            # The existing server is alive. Do not create a duplicate browser
            # tab merely because Windows refused a foreground request.
            return True
    return False


def _runtime_browser_fields(browser: ManagedBrowser | None) -> dict:
    if browser is None:
        return {
            "browser_pid": 0,
            "browser_hwnd": 0,
            "browser_name": "system browser",
            "browser_executable": "",
            "browser_mode": "default",
        }
    return {
        "browser_pid": int(browser.root_pid),
        "browser_hwnd": int(browser.hwnd or 0),
        "browser_name": browser.name,
        "browser_executable": str(browser.executable or ""),
        "browser_mode": "app",
    }


def _launch_browser(project_dir: Path, url: str, *, use_default_browser: bool) -> ManagedBrowser | None:
    if not use_default_browser:
        browser = _open_managed_browser_window(project_dir, url)
        if browser is not None:
            _focus_browser(browser)
            return browser
    _open_default_browser(url)
    if not use_default_browser:
        print("Edge and Chrome app mode were unavailable; the system browser was used instead.")
    return None


def _browser_closed(browser: ManagedBrowser | None) -> bool:
    if browser is None:
        return False
    if browser.hwnd:
        return not _window_exists(browser.hwnd)
    if browser.process is not None and browser.process.poll() is not None:
        return True
    return False


def _restart_server(
    project_dir: Path,
    data_home: Path,
    venv_python: Path,
    session: ManagedServer,
    browser: ManagedBrowser | None,
    control: LauncherControlServer,
    *,
    use_default_browser: bool,
) -> tuple[ManagedServer | None, ManagedBrowser | None, Path]:
    preferred_port = session.port
    old_url = session.url
    _write_runtime_state(status="restarting")
    print("Restart requested by the application.")
    _stop_server(session, control.token, action="restart")

    try:
        apply_staged_updates_before_start(project_dir, data_home)
        venv_python = ensure_environment(project_dir)
        same_port_available = _wait_for_port_release(APP_HOST, preferred_port, timeout_seconds=12.0)
        port = preferred_port if same_port_available else _choose_available_port(APP_HOST, preferred_port)
        replacement = _start_server(
            project_dir,
            venv_python,
            data_home=data_home,
            host=APP_HOST,
            port=port,
            control=control,
        )
    except Exception as exc:
        log_path = _launcher_log_path(data_home)
        print(f"Restart failed: {exc}")
        _print_log_tail(log_path)
        _write_runtime_state(status="restart_failed", error=str(exc), server_pid=0)
        _fatal_message(
            "Money Manager could not restart automatically. The existing data was not moved or replaced.\n\n"
            f"Reason: {exc}",
            log_path=log_path,
        )
        return None, browser, venv_python

    if browser is None:
        browser = _launch_browser(project_dir, replacement.url, use_default_browser=use_default_browser)
    elif replacement.url != old_url:
        _stop_browser(browser)
        browser = _launch_browser(project_dir, replacement.url, use_default_browser=use_default_browser)
    else:
        _focus_browser(browser, retry_seconds=5.0)

    fields = _runtime_browser_fields(browser)
    _write_runtime_state(
        status="ready",
        server_pid=int(replacement.process.pid),
        host=replacement.host,
        port=replacement.port,
        url=replacement.url,
        server_instance_id=replacement.instance_id,
        **fields,
    )
    return replacement, browser, venv_python


def start_app(
    project_dir: Path,
    venv_python: Path,
    *,
    data_home: Path,
    use_default_browser: bool = False,
    preferred_port: int = APP_PORT,
) -> int:
    control = LauncherControlServer()
    session: ManagedServer | None = None
    browser: ManagedBrowser | None = None
    port = _choose_available_port(APP_HOST, preferred_port)
    _write_runtime_state(
        status="starting",
        launcher_pid=os.getpid(),
        project_dir=str(project_dir),
        data_home=str(data_home),
        host=APP_HOST,
        port=port,
        url=_app_url(APP_HOST, port),
        hidden=_HIDDEN_MODE,
    )

    try:
        session = _start_server(
            project_dir,
            venv_python,
            data_home=data_home,
            host=APP_HOST,
            port=port,
            control=control,
        )
        browser = _launch_browser(project_dir, session.url, use_default_browser=use_default_browser)
        fields = _runtime_browser_fields(browser)
        _write_runtime_state(
            status="ready",
            launcher_pid=os.getpid(),
            server_pid=int(session.process.pid),
            host=session.host,
            port=session.port,
            url=session.url,
            server_instance_id=session.instance_id,
            project_dir=str(project_dir),
            data_home=str(data_home),
            **fields,
        )

        while True:
            if session is not None and session.process.poll() is not None:
                code = int(session.process.returncode or 0)
                _write_runtime_state(status="server_stopped", server_pid=0, exit_code=code)
                if code != 0:
                    _print_log_tail(session.log_path)
                    _fatal_message("The Money Manager server stopped unexpectedly.", log_path=session.log_path)
                return code

            if _browser_closed(browser):
                print("The app window was closed. Stopping the local server.")
                return _stop_server(session, control.token, action="shutdown")

            command = control.get(timeout=0.3)
            if not command:
                continue
            action = str(command.get("command") or "")
            if action == "focus":
                if browser is not None:
                    _focus_browser(browser, retry_seconds=3.0)
                    _write_runtime_state(browser_hwnd=int(browser.hwnd or 0))
                continue
            if action == "shutdown":
                return _stop_server(session, control.token, action="shutdown")
            if action == "restart" and session is not None:
                session, browser, venv_python = _restart_server(
                    project_dir,
                    data_home,
                    venv_python,
                    session,
                    browser,
                    control,
                    use_default_browser=use_default_browser,
                )
                if session is None:
                    return 1
    except KeyboardInterrupt:
        print("Stopping Money Manager...")
        return _stop_server(session, control.token, action="shutdown")
    finally:
        if session is not None and session.process.poll() is None:
            _stop_server(session, control.token, action="shutdown")
        control.close()
        _clear_runtime_state()


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start Money Manager as a local desktop application.")
    parser.add_argument("--project-dir", help="Money Manager repository folder.")
    parser.add_argument("--data-home", help="Existing MoneyManagerData folder; launcher config is used when omitted.")
    parser.add_argument(
        "--default-browser",
        action="store_true",
        help="Use the system browser instead of Edge/Chrome app mode.",
    )
    parser.add_argument(
        "--port",
        default=APP_PORT,
        type=int,
        help=f"Preferred local port. Default: {APP_PORT}.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--hidden", action="store_true", help="Run without a console window (normal Windows mode).")
    mode.add_argument("--console", action="store_true", help="Keep visible diagnostic output in the current console.")
    parser.add_argument("--foreground", action="store_true", help="Legacy alias for --console.")
    return parser.parse_args(argv)


def _determine_hidden_mode(argv: list[str]) -> bool:
    if "--console" in argv or "--foreground" in argv:
        return False
    if "--hidden" in argv:
        return True
    if os.name == "nt" and str(sys.executable or "").casefold().endswith("pythonw.exe"):
        return True
    if getattr(sys, "frozen", False) and (sys.stdout is None or sys.stderr is None):
        return True
    return False


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)
    if not _acquire_single_instance():
        focused = _focus_existing_instance()
        if not focused and not _HIDDEN_MODE:
            print("Money Manager is already starting or running.")
        return 0

    try:
        project_dir = project_dir_from_arg(args.project_dir) if args.project_dir else find_project_dir()
        data_home = _resolve_data_home(project_dir, args.data_home)
        _warn_about_data_home(project_dir, data_home)
        ensure_data_home(project_dir, data_home)
        print(f"Using project folder: {project_dir}")
        print(f"Using data folder: {data_home}")
        print(f"Launcher configuration: {_config_path()}")
        print(f"Browser profile: {_browser_profile_dir(project_dir)}")

        apply_staged_updates_before_start(project_dir, data_home)
        venv_python = ensure_environment(project_dir)
        return start_app(
            project_dir,
            venv_python,
            data_home=data_home,
            use_default_browser=bool(args.default_browser),
            preferred_port=int(args.port or APP_PORT),
        )
    finally:
        _release_single_instance()


def _entrypoint() -> int:
    argv = list(sys.argv[1:])
    hidden = _determine_hidden_mode(argv)
    _prepare_output(hidden)
    try:
        return main(argv)
    except SystemExit as exc:
        code = int(exc.code or 0)
        if code and hidden:
            _fatal_message("Startup was cancelled or could not continue.")
        return code
    except Exception as exc:
        print(f"Launcher error: {exc}")
        if hidden:
            _fatal_message(str(exc), log_path=_user_config_dir() / BOOTSTRAP_LOG_FILE_NAME)
        else:
            raise
        return 1
    finally:
        _release_single_instance()
        _close_output()


if __name__ == "__main__":
    raise SystemExit(_entrypoint())
