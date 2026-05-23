#!/usr/bin/env python3
"""
104 Launcher backend logic shared by UI frontends.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import ctypes
import webbrowser
import winreg
from tkinter import messagebox
from typing import Optional

from bs4 import BeautifulSoup

from version import LAUNCHER_VERSION

PRESET_URL = "https://raw.githubusercontent.com/ltsammy/strikeplatoon/refs/heads/main/modlist.html"
SERVER_IP = "94.199.215.95"
SERVER_PORT = "2302"
SERVER_PW = "jimmy"
TS3_IP = "94.199.215.95"
TS3_PORT = "9987"
TS3_DOWNLOAD_URL = "https://www.teamspeak.com/de/downloads/#ts3client"
TFAR_PLUGIN_DOWNLOAD_URL = "https://github.com/ltsammy/strikeplatoon/raw/refs/heads/main/task_force_radio.ts3_plugin"
DISCORD_URL = "https://discord.gg/ageofclones"
GITHUB_REPO = "ltsammy/strikeplatoon"
GITHUB_API_LATEST_RELEASE_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"
LAUNCHER_ASSET_NAMES = ("launcher.exe", "104Launcher.exe")
GITHUB_API_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "104Launcher",
}
ARMA3_APP_ID = "107410"

local_app_data = os.environ.get("LOCALAPPDATA")
if not local_app_data:
    local_app_data = os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), "AppData", "Local")

APP_INSTALL_DIR = os.path.join(local_app_data, "104Launcher")
INSTALLED_EXE_PATH = os.path.join(APP_INSTALL_DIR, "launcher.exe")
START_MENU_DIR = os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")),
    "Microsoft",
    "Windows",
    "Start Menu",
    "Programs",
    "104Launcher",
)
UNINSTALL_SCRIPT_PATH = os.path.join(APP_INSTALL_DIR, "uninstall.cmd")
UNINSTALL_REG_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\StrikePlatoonArma3"

APP_BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
LOGO_PNG_PATH = os.path.join(APP_BASE_DIR, "logo.png")
LOGO_ICO_PATH = os.path.join(APP_BASE_DIR, "logo.ico")
BACKGROUND_IMAGE_PATH = os.path.join(APP_BASE_DIR, "background.jpg")
SERVER_QUERY_PORTS = (int(SERVER_PORT), int(SERVER_PORT) + 1)


def _get_config_file() -> str:
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        cfg_dir = os.path.join(appdata, "104Launcher")
    else:
        cfg_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    os.makedirs(cfg_dir, exist_ok=True)
    return os.path.join(cfg_dir, "config.json")


CONFIG_FILE = _get_config_file()

DEFAULT_CONFIG = {
    "arma3_exe": "",
    "teamspeak_exe": "",
    "teamspeak_plugins_dir": "",
}


def load_config() -> dict:
    if not os.path.isfile(CONFIG_FILE):
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return {**DEFAULT_CONFIG, **data}
    except (OSError, json.JSONDecodeError):
        return DEFAULT_CONFIG.copy()


def save_config(cfg: dict) -> None:
    merged = {**DEFAULT_CONFIG, **cfg}
    with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
        json.dump(merged, fh, indent=2, ensure_ascii=False)


def ensure_admin_rights() -> bool:
    if os.name != "nt":
        return True

    try:
        is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        is_admin = False

    if is_admin:
        return True

    elevate_now = messagebox.askyesno(
        "Administratorrechte erforderlich",
        "Der Launcher benoetigt Administratorrechte. Jetzt mit Administratorrechten neu starten?",
    )
    if not elevate_now:
        return False

    try:
        launched = False

        def _runas_shell_execute(executable: str, params: str, working_dir: str) -> bool:
            rc = ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                executable,
                params,
                working_dir,
                1,
            )
            return rc > 32

        def _runas_via_cmd(executable: str, args: list[str], working_dir: str) -> bool:
            # cmd/start fallback is robust for debug runs where direct argument passing can fail.
            full_cmd = subprocess.list2cmdline([executable, *args])
            cmd_params = f'/c start "" {full_cmd}'
            rc = ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                "cmd.exe",
                cmd_params,
                working_dir,
                0,
            )
            return rc > 32

        if getattr(sys, "frozen", False):
            executable = os.path.abspath(sys.executable)
            params = subprocess.list2cmdline(sys.argv[1:])
            working_dir = os.path.dirname(executable)
            launched = _runas_shell_execute(executable, params, working_dir)
            if not launched:
                launched = _runas_via_cmd(executable, sys.argv[1:], working_dir)
        else:
            python_exe = os.path.abspath(sys.executable)
            script_path = os.path.abspath(sys.argv[0])
            args = [script_path, *sys.argv[1:]]
            params = subprocess.list2cmdline(args)
            working_dir = os.path.dirname(script_path)
            launched = _runas_shell_execute(python_exe, params, working_dir)
            if not launched:
                launched = _runas_via_cmd(python_exe, args, working_dir)

        if not launched:
            messagebox.showerror(
                "Administratorrechte",
                "Der Launcher konnte nicht mit Administratorrechten gestartet werden.",
            )
            return False

        # Neue erhoehte Instanz laeuft bereits; aktuelle Instanz beenden.
        return False
    except Exception as exc:
        messagebox.showerror(
            "Administratorrechte",
            f"Der Launcher konnte nicht mit Administratorrechten gestartet werden:\n{exc}",
        )
        return False


def _current_executable_path() -> str:
    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable)
    return os.path.abspath(__file__)


def _create_shortcut(shortcut_path: str, target_path: str, icon_path: str) -> None:
    os.makedirs(os.path.dirname(shortcut_path), exist_ok=True)

    def _ps_escape(value: str) -> str:
        return value.replace("'", "''")

    ps_script = (
        "$WshShell = New-Object -ComObject WScript.Shell\n"
        f"$Shortcut = $WshShell.CreateShortcut('{_ps_escape(shortcut_path)}')\n"
        f"$Shortcut.TargetPath = '{_ps_escape(target_path)}'\n"
        f"$Shortcut.WorkingDirectory = '{_ps_escape(os.path.dirname(target_path))}'\n"
        f"$Shortcut.IconLocation = '{_ps_escape(icon_path)},0'\n"
        "$Shortcut.Save()\n"
    )

    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
        check=True,
        capture_output=True,
        text=True,
    )


def _write_uninstall_script() -> None:
    desktop_dir = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")
    desktop_new = os.path.join(desktop_dir, "Strike Platoon Arma 3.lnk")
    desktop_old = os.path.join(desktop_dir, "104 Launcher.lnk")
    startmenu_new = os.path.join(START_MENU_DIR, "Strike Platoon Arma 3.lnk")
    startmenu_old = os.path.join(START_MENU_DIR, "104 Launcher.lnk")

    script = (
        "@echo off\n"
        "setlocal\n"
        "taskkill /F /IM launcher.exe >nul 2>&1\n"
        f"del /Q \"{desktop_new}\" >nul 2>&1\n"
        f"del /Q \"{desktop_old}\" >nul 2>&1\n"
        f"del /Q \"{startmenu_new}\" >nul 2>&1\n"
        f"del /Q \"{startmenu_old}\" >nul 2>&1\n"
        f"rmdir /S /Q \"{START_MENU_DIR}\" >nul 2>&1\n"
        f"reg delete \"HKCU\\{UNINSTALL_REG_KEY}\" /f >nul 2>&1\n"
        f"start \"\" cmd /c \"timeout /t 2 /nobreak >nul & rmdir /S /Q \"\"{APP_INSTALL_DIR}\"\"\"\n"
        "endlocal\n"
    )

    with open(UNINSTALL_SCRIPT_PATH, "w", encoding="utf-8") as fh:
        fh.write(script)


def _register_uninstall_entry() -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_REG_KEY) as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "Strike Platoon Arma 3")
        winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, LAUNCHER_VERSION)
        winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "Strike Platoon")
        winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, APP_INSTALL_DIR)
        winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, INSTALLED_EXE_PATH)
        winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, f'"{UNINSTALL_SCRIPT_PATH}"')
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)


def _install_launcher_if_needed() -> bool:
    if not getattr(sys, "frozen", False):
        return True

    current_exe = _current_executable_path()
    if os.path.normcase(current_exe) == os.path.normcase(INSTALLED_EXE_PATH):
        return True

    install_now = messagebox.askyesno(
        "Launcher installieren",
        "Launcher soll fuer diesen Benutzer installiert werden. Jetzt installieren?",
    )
    if not install_now:
        return True

    try:
        os.makedirs(APP_INSTALL_DIR, exist_ok=True)
        shutil.copy2(current_exe, INSTALLED_EXE_PATH)

        desktop_dir = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop")
        desktop_shortcut = os.path.join(desktop_dir, "Strike Platoon Arma 3.lnk")
        startmenu_shortcut = os.path.join(START_MENU_DIR, "Strike Platoon Arma 3.lnk")

        create_desktop = messagebox.askyesno(
            "Desktop-Verknuepfung",
            "Desktop-Verknuepfung erstellen?",
        )
        if create_desktop:
            _create_shortcut(desktop_shortcut, INSTALLED_EXE_PATH, INSTALLED_EXE_PATH)

        create_startmenu = messagebox.askyesno(
            "Startmenue-Verknuepfung",
            "Startmenue-Verknuepfung erstellen?",
        )
        if create_startmenu:
            _create_shortcut(startmenu_shortcut, INSTALLED_EXE_PATH, INSTALLED_EXE_PATH)

        _write_uninstall_script()
        _register_uninstall_entry()

        messagebox.showinfo(
            "Installation abgeschlossen",
            "Launcher wurde installiert und wird jetzt aus dem Benutzerprofil gestartet.",
        )
        subprocess.Popen([INSTALLED_EXE_PATH], cwd=APP_INSTALL_DIR)
        return False
    except Exception as exc:
        messagebox.showerror("Installation fehlgeschlagen", f"Installation fehlgeschlagen:\n{exc}")
        return True


def find_steam_path() -> Optional[str]:
    entries = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Valve\Steam", "SteamPath"),
    ]
    for hive, key_path, value_name in entries:
        try:
            with winreg.OpenKey(hive, key_path) as key:
                value, _ = winreg.QueryValueEx(key, value_name)
                if os.path.isdir(str(value)):
                    return str(value)
        except OSError:
            continue
    return None


def find_all_steam_libraries(steam_path: str) -> list[str]:
    default = os.path.join(steam_path, "steamapps")
    libraries: list[str] = []
    if os.path.isdir(default):
        libraries.append(default)

    vdf = os.path.join(default, "libraryfolders.vdf")
    if os.path.isfile(vdf):
        try:
            with open(vdf, "r", encoding="utf-8") as fh:
                content = fh.read()
            for raw in re.findall(r'"path"\s+"([^"]+)"', content):
                candidate = os.path.join(raw.replace("\\\\", "\\"), "steamapps")
                if os.path.isdir(candidate) and candidate not in libraries:
                    libraries.append(candidate)
        except OSError:
            pass
    return libraries


def find_arma3(steam_path: str) -> tuple[Optional[str], Optional[str]]:
    for steamapps in find_all_steam_libraries(steam_path):
        for exe_name in ("arma3_x64.exe", "arma3.exe"):
            exe = os.path.join(steamapps, "common", "Arma 3", exe_name)
            if os.path.isfile(exe):
                workshop = os.path.join(steamapps, "workshop", "content", ARMA3_APP_ID)
                return exe, workshop
    return None, None


def find_teamspeak_exe() -> Optional[str]:
    registry_entries = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\TeamSpeak 3 Client", ["InstallDir", "InstallLocation"]),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\TeamSpeak 3 Client", ["InstallDir", "InstallLocation"]),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\TeamSpeak 3 Client", ["InstallDir", "InstallLocation"]),
    ]

    exe_names = ("ts3client_win64.exe", "ts3client_win32.exe")
    for hive, key_path, value_names in registry_entries:
        try:
            with winreg.OpenKey(hive, key_path) as key:
                for value_name in value_names:
                    try:
                        install_dir, _ = winreg.QueryValueEx(key, value_name)
                    except OSError:
                        continue
                    for exe_name in exe_names:
                        candidate = os.path.join(str(install_dir), exe_name)
                        if os.path.isfile(candidate):
                            return candidate
        except OSError:
            continue

    fallback_dirs = [
        os.path.join(os.environ.get("ProgramFiles", ""), "TeamSpeak 3 Client"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "TeamSpeak 3 Client"),
    ]
    for directory in fallback_dirs:
        for exe_name in exe_names:
            candidate = os.path.join(directory, exe_name)
            if os.path.isfile(candidate):
                return candidate
    return None


def parse_preset(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    mods: list[dict] = []
    for row in soup.find_all("tr", attrs={"data-type": "ModContainer"}):
        name_td = row.find("td", attrs={"data-type": "DisplayName"})
        link_a = row.find("a", attrs={"data-type": "Link"})
        if not (name_td and link_a):
            continue
        href = link_a.get("href", "")
        match = re.search(r"[?&]id=(\d+)", href)
        if match:
            mods.append({"name": name_td.get_text(strip=True), "id": match.group(1)})
    return mods
