#!/usr/bin/env python3
"""
104 Launcher - Custom Arma 3 Launcher
"""

import glob
import csv
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
import winreg
from tkinter import filedialog, messagebox
from typing import Optional

import customtkinter as ctk
import requests
from bs4 import BeautifulSoup
from PIL import Image

from version import LAUNCHER_VERSION

# ---------------------------------------------------------------------------
# Hardcoded Konfiguration
# ---------------------------------------------------------------------------

PRESET_URL    = "https://raw.githubusercontent.com/ltsammy/strikeplatoon/refs/heads/main/modlist.html"
SERVER_IP     = "94.199.215.95"
SERVER_PORT   = "2302"
SERVER_PW     = "jimmy"
TS3_IP        = "94.199.215.95"
TS3_PORT      = "9987"
TS3_DOWNLOAD_URL = "https://www.teamspeak.com/de/downloads/#ts3client"
TFAR_PLUGIN_DOWNLOAD_URL = "https://github.com/ltsammy/strikeplatoon/raw/refs/heads/main/task_force_radio.ts3_plugin"
GITHUB_REPO = "ltsammy/strikeplatoon"
GITHUB_API_LATEST_RELEASE_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"
LAUNCHER_ASSET_NAMES = ("launcher.exe", "104Launcher.exe")
GITHUB_API_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "104Launcher",
}
STEAM_WEBAPI_KEY_URL = "https://steamcommunity.com/dev/apikey"
ARMA3_APP_ID  = "107410"
APP_INSTALL_DIR = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "104Launcher")
INSTALLED_EXE_PATH = os.path.join(APP_INSTALL_DIR, "launcher.exe")
START_MENU_DIR = os.path.join(
    os.environ.get("ProgramData", r"C:\ProgramData"),
    "Microsoft",
    "Windows",
    "Start Menu",
    "Programs",
    "104Launcher",
)
UNINSTALL_SCRIPT_PATH = os.path.join(APP_INSTALL_DIR, "uninstall.cmd")
UNINSTALL_REG_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\StrikePlatoonArma3"

# PyInstaller onefile: Assets liegen zur Laufzeit in _MEIPASS.
APP_BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
LOGO_PNG_PATH = os.path.join(APP_BASE_DIR, "logo.png")
LOGO_ICO_PATH = os.path.join(APP_BASE_DIR, "logo.ico")


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
    "steam_webapi_key": "",
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
    """Stellt sicher, dass der Launcher mit Adminrechten laeuft."""
    try:
        is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        is_admin = False

    if is_admin:
        return True

    try:
        params = " ".join(f'"{arg}"' for arg in sys.argv[1:])
        rc = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            sys.executable,
            params,
            None,
            1,
        )
        # ShellExecuteW > 32 bedeutet Erfolg.
        if rc <= 32:
            messagebox.showerror(
                "Adminrechte erforderlich",
                "Der Launcher braucht Administratorrechte. Bitte als Administrator starten.",
            )
        return False
    except Exception:
        messagebox.showerror(
            "Adminrechte erforderlich",
            "Der Launcher braucht Administratorrechte. Bitte als Administrator starten.",
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
        f"reg delete \"HKLM\\{UNINSTALL_REG_KEY}\" /f >nul 2>&1\n"
        f"start \"\" cmd /c \"timeout /t 2 /nobreak >nul & rmdir /S /Q \"\"{APP_INSTALL_DIR}\"\"\"\n"
        "endlocal\n"
    )

    with open(UNINSTALL_SCRIPT_PATH, "w", encoding="utf-8") as fh:
        fh.write(script)


def _register_uninstall_entry() -> None:
    with winreg.CreateKey(winreg.HKEY_LOCAL_MACHINE, UNINSTALL_REG_KEY) as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, "Strike Platoon Arma 3")
        winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, LAUNCHER_VERSION)
        winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "Strike Platoon")
        winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, APP_INSTALL_DIR)
        winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, INSTALLED_EXE_PATH)
        winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, f'"{UNINSTALL_SCRIPT_PATH}"')
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)


def _install_launcher_if_needed() -> bool:
    """Installiert die EXE nach Program Files und erstellt optional Verknüpfungen.

    Returns:
        True: normal weiterlaufen
        False: aktuelle Instanz beenden (weil installierte Instanz gestartet wurde)
    """
    if not getattr(sys, "frozen", False):
        return True

    current_exe = _current_executable_path()
    if os.path.normcase(current_exe) == os.path.normcase(INSTALLED_EXE_PATH):
        return True

    install_now = messagebox.askyesno(
        "Launcher installieren",
        "Launcher soll unter 'Programme' installiert werden. Jetzt installieren?",
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
            "Desktop-Verknüpfung",
            "Desktop-Verknüpfung erstellen?",
        )
        if create_desktop:
            _create_shortcut(desktop_shortcut, INSTALLED_EXE_PATH, INSTALLED_EXE_PATH)

        create_startmenu = messagebox.askyesno(
            "Startmenü-Verknüpfung",
            "Startmenü-Verknüpfung erstellen?",
        )
        if create_startmenu:
            _create_shortcut(startmenu_shortcut, INSTALLED_EXE_PATH, INSTALLED_EXE_PATH)

        _write_uninstall_script()
        _register_uninstall_entry()

        messagebox.showinfo(
            "Installation abgeschlossen",
            "Launcher wurde installiert und wird jetzt aus 'Programme' gestartet.",
        )
        subprocess.Popen([INSTALLED_EXE_PATH], cwd=APP_INSTALL_DIR)
        return False
    except Exception as exc:
        messagebox.showerror("Installation fehlgeschlagen", f"Installation fehlgeschlagen:\n{exc}")
        return True

# ---------------------------------------------------------------------------
# Steam / Arma 3 Erkennung
# ---------------------------------------------------------------------------

def find_steam_path() -> Optional[str]:
    entries = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam",             "InstallPath"),
        (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Valve\Steam",             "SteamPath"),
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
    """TeamSpeak 3 Client EXE in Registry und Standardpfaden suchen."""
    registry_entries = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\TeamSpeak 3 Client", ["InstallDir", "InstallLocation"]),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\TeamSpeak 3 Client", ["InstallDir", "InstallLocation"]),
        (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\TeamSpeak 3 Client", ["InstallDir", "InstallLocation"]),
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

    # Fallback: typische Installationspfade
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


# ---------------------------------------------------------------------------
# Preset-Parser
# ---------------------------------------------------------------------------

def parse_preset(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    mods: list[dict] = []
    for row in soup.find_all("tr", attrs={"data-type": "ModContainer"}):
        name_td = row.find("td", attrs={"data-type": "DisplayName"})
        link_a  = row.find("a",  attrs={"data-type": "Link"})
        if not (name_td and link_a):
            continue
        href  = link_a.get("href", "")
        match = re.search(r"[?&]id=(\d+)", href)
        if match:
            mods.append({"name": name_td.get_text(strip=True), "id": match.group(1)})
    return mods


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class LauncherApp(ctk.CTk):

    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.ts_proc: Optional[subprocess.Popen] = None
        self.ts_url_pid: Optional[int] = None
        self.cfg = load_config()
        self.log_visible = False
        self.logo_image = None
        self.selected_arma_exe = ""
        self.selected_ts_exe = ""
        self.selected_ts_plugins_dir = ""
        self.selected_steam_webapi_key = ""

        self.title("Strike Platoon | Arma 3 Launcher")
        self._set_window_icon()
        self.geometry("980x760")
        self.resizable(True, True)
        self._build_ui()
        self.after(800, lambda: threading.Thread(target=self._check_launcher_update, daemon=True).start())

    def _set_window_icon(self) -> None:
        """Setzt das Fenster-Icon (Titelleiste/Taskbar) auf das Projektlogo."""
        try:
            if os.path.isfile(LOGO_ICO_PATH):
                self.iconbitmap(LOGO_ICO_PATH)
        except Exception:
            pass

    def _build_ui(self) -> None:
        self.configure(fg_color="#0b1018")

        # Hero-Bereich
        hero = ctk.CTkFrame(self, fg_color="#101a2a", corner_radius=18)
        hero.pack(fill="x", padx=18, pady=(18, 10))
        hero.columnconfigure(1, weight=1)

        if os.path.isfile(LOGO_PNG_PATH):
            try:
                logo_pil = Image.open(LOGO_PNG_PATH)
                self.logo_image = ctk.CTkImage(light_image=logo_pil, dark_image=logo_pil, size=(84, 84))
                ctk.CTkLabel(hero, image=self.logo_image, text="").grid(
                    row=0, column=0, rowspan=2, padx=(18, 14), pady=14
                )
            except Exception:
                pass

        ctk.CTkLabel(
            hero,
            text="Strike Platoon | Arma 3 Launcher",
            font=ctk.CTkFont(size=30, weight="bold"),
            text_color="#f7f4e8",
        ).grid(row=0, column=1, padx=(0, 16), pady=(16, 2), sticky="w")

        ctk.CTkLabel(
            hero,
            text=f"Direktstart mit Preset, Server {SERVER_IP}:{SERVER_PORT}",
            font=ctk.CTkFont(size=14),
            text_color="#8cb6d6",
        ).grid(row=1, column=1, padx=(0, 16), pady=(0, 16), sticky="w")

        # Pfad-Karte
        path_frame = ctk.CTkFrame(self, fg_color="#121f33", corner_radius=14)
        path_frame.pack(fill="x", padx=18, pady=(2, 10))

        ctk.CTkLabel(path_frame, text="Arma 3 EXE", width=120, anchor="w", text_color="#c9d8e8").grid(
            row=0, column=0, padx=(14, 8), pady=(12, 6), sticky="w"
        )
        self.ent_arma = ctk.CTkEntry(path_frame, fg_color="#0d1524", border_color="#27405f")
        self.ent_arma.grid(row=0, column=1, padx=6, pady=(12, 6), sticky="ew")

        ctk.CTkButton(
            path_frame, text="...", width=36, command=self._browse_arma,
            fg_color="#254367", hover_color="#315781"
        ).grid(row=0, column=2, padx=(6, 8), pady=(12, 6))

        ctk.CTkLabel(path_frame, text="TS3 EXE", width=120, anchor="w", text_color="#c9d8e8").grid(
            row=1, column=0, padx=(14, 8), pady=(0, 12), sticky="w"
        )
        self.ent_ts = ctk.CTkEntry(path_frame, fg_color="#0d1524", border_color="#27405f")
        self.ent_ts.grid(row=1, column=1, padx=6, pady=(0, 12), sticky="ew")

        ctk.CTkButton(
            path_frame, text="...", width=36, command=self._browse_ts,
            fg_color="#254367", hover_color="#315781"
        ).grid(row=1, column=2, padx=(6, 8), pady=(0, 12))

        ctk.CTkLabel(path_frame, text="TS3 Pluginpfad", width=120, anchor="w", text_color="#c9d8e8").grid(
            row=2, column=0, padx=(14, 8), pady=(0, 12), sticky="w"
        )
        self.ent_ts_plugins = ctk.CTkEntry(path_frame, fg_color="#0d1524", border_color="#27405f")
        self.ent_ts_plugins.grid(row=2, column=1, padx=6, pady=(0, 12), sticky="ew")

        ctk.CTkButton(
            path_frame, text="...", width=36, command=self._browse_ts_plugins,
            fg_color="#254367", hover_color="#315781"
        ).grid(row=2, column=2, padx=(6, 8), pady=(0, 12))

        ctk.CTkButton(
            path_frame, text="Auto erkennen", width=130, command=self._auto_detect_paths,
            fg_color="#375a2d", hover_color="#466f39"
        ).grid(row=0, column=3, padx=(6, 14), pady=(12, 6))
        ctk.CTkButton(
            path_frame, text="Pfade speichern", width=130, command=self._save_paths,
            fg_color="#375a2d", hover_color="#466f39"
        ).grid(row=1, column=3, padx=(6, 14), pady=(0, 12))

        ctk.CTkLabel(path_frame, text="Steam WebAPI Key", width=120, anchor="w", text_color="#c9d8e8").grid(
            row=3, column=0, padx=(14, 8), pady=(0, 12), sticky="w"
        )
        self.ent_steam_webapi_key = ctk.CTkEntry(
            path_frame,
            fg_color="#0d1524",
            border_color="#27405f",
            show="*",
        )
        self.ent_steam_webapi_key.grid(row=3, column=1, padx=6, pady=(0, 12), sticky="ew")

        ctk.CTkButton(
            path_frame,
            text="Key holen",
            width=90,
            command=lambda: webbrowser.open(STEAM_WEBAPI_KEY_URL),
            fg_color="#254367",
            hover_color="#315781",
        ).grid(row=3, column=2, padx=(6, 8), pady=(0, 12))

        path_frame.columnconfigure(1, weight=1)

        # Aktionsleiste
        action_frame = ctk.CTkFrame(self, fg_color="transparent")
        action_frame.pack(fill="x", padx=18, pady=(0, 8))

        self.log_btn = ctk.CTkButton(
            action_frame,
            text="Arma3 Logordner",
            width=140, height=44,
            font=ctk.CTkFont(size=12),
            fg_color="#3e3d52", hover_color="#4f4e66",
            command=self._open_log_folder,
        )
        self.log_btn.pack(side="left")

        self.toggle_log_btn = ctk.CTkButton(
            action_frame,
            text="Log anzeigen",
            width=120, height=44,
            font=ctk.CTkFont(size=12),
            fg_color="#5f4a1f", hover_color="#775d2a",
            command=self._toggle_log_visibility,
        )
        self.toggle_log_btn.pack(side="left", padx=(8, 0))

        self.launch_btn = ctk.CTkButton(
            action_frame,
            text="SPIEL STARTEN",
            width=260, height=50,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color="#2b8e49", hover_color="#236f3a",
            command=self._start_launch,
        )
        self.launch_btn.pack(side="right")

        # Status
        self.status_lbl = ctk.CTkLabel(
            self,
            text="Bereit",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#95b9d8",
        )
        self.status_lbl.pack(anchor="w", padx=22, pady=(0, 6))

        # Log (initial versteckt)
        self.log_box = ctk.CTkTextbox(
            self,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color="#0b1422",
            border_color="#223c5c",
            border_width=1,
            height=260,
        )
        self.log_box.configure(state="disabled")

        self._load_paths_into_ui()

    def _toggle_log_visibility(self) -> None:
        self.log_visible = not self.log_visible
        if self.log_visible:
            self.log_box.pack(fill="both", expand=True, padx=18, pady=(0, 16))
            self.toggle_log_btn.configure(text="Log verstecken")
        else:
            self.log_box.pack_forget()
            self.toggle_log_btn.configure(text="Log anzeigen")

    def _log(self, msg: str) -> None:
        if not hasattr(self, "log_box"):
            return
        self.log_box.configure(state="normal")
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _ask_yes_no_threadsafe(self, title: str, question: str) -> bool:
        """Frage-Dialog auf dem UI-Thread anzeigen und Ergebnis zurueckgeben."""
        result = {"value": False}
        done = threading.Event()

        def _show_dialog() -> None:
            try:
                result["value"] = bool(messagebox.askyesno(title, question, parent=self))
            except Exception:
                result["value"] = False
            finally:
                done.set()

        self.after(0, _show_dialog)
        done.wait()
        return result["value"]

    def _open_missing_mods_in_steam(self, missing_mods: list[dict]) -> None:
        """Fehlende Mods im Steam Workshop oeffnen, damit man sie abonnieren kann."""
        for mod in missing_mods:
            mod_id = mod.get("id", "")
            mod_name = mod.get("name", "Unbekannt")
            steam_url = f"steam://url/CommunityFilePage/{mod_id}"
            web_url = f"https://steamcommunity.com/sharedfiles/filedetails/?id={mod_id}"
            opened = webbrowser.open(steam_url)
            if not opened:
                webbrowser.open(web_url)
            self._log(f"[INFO] Workshop geoeffnet: {mod_name} ({mod_id})")

    def _set_status(self, text: str, color: str = "#546e7a") -> None:
        self.status_lbl.configure(text=text, text_color=color)

    def _open_log_folder(self) -> None:
        log_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Arma 3")
        if os.path.isdir(log_dir):
            os.startfile(log_dir)
            self._log(f"[INFO] Log-Ordner geoeffnet: {log_dir}")
        else:
            self._log(f"[WARN] Log-Ordner nicht gefunden: {log_dir}")

    def _load_paths_into_ui(self) -> None:
        arma_cfg = self.cfg.get("arma3_exe", "")
        ts_cfg = self.cfg.get("teamspeak_exe", "")
        plugins_cfg = self.cfg.get("teamspeak_plugins_dir", "")
        webapi_cfg = self.cfg.get("steam_webapi_key", "")

        if arma_cfg and os.path.isfile(arma_cfg):
            self.ent_arma.delete(0, "end")
            self.ent_arma.insert(0, arma_cfg)

        if ts_cfg and os.path.isfile(ts_cfg):
            self.ent_ts.delete(0, "end")
            self.ent_ts.insert(0, ts_cfg)

        if plugins_cfg and os.path.isdir(plugins_cfg):
            self.ent_ts_plugins.delete(0, "end")
            self.ent_ts_plugins.insert(0, plugins_cfg)

        if webapi_cfg:
            self.ent_steam_webapi_key.delete(0, "end")
            self.ent_steam_webapi_key.insert(0, webapi_cfg)

        if not self.ent_arma.get().strip() or not self.ent_ts.get().strip() or not self.ent_ts_plugins.get().strip():
            self._auto_detect_paths(save=False)

    def _save_paths(self) -> None:
        arma_path = self.ent_arma.get().strip()
        ts_path = self.ent_ts.get().strip()
        ts_plugins_path = self.ent_ts_plugins.get().strip()
        steam_webapi_key = self.ent_steam_webapi_key.get().strip()
        self.cfg["arma3_exe"] = arma_path
        self.cfg["teamspeak_exe"] = ts_path
        self.cfg["teamspeak_plugins_dir"] = ts_plugins_path
        self.cfg["steam_webapi_key"] = steam_webapi_key
        save_config(self.cfg)
        self._log("[OK] Pfade gespeichert.")

    def _browse_arma(self) -> None:
        file_path = filedialog.askopenfilename(
            title="Arma 3 EXE auswählen",
            filetypes=[("Executable", "*.exe")],
        )
        if file_path:
            self.ent_arma.delete(0, "end")
            self.ent_arma.insert(0, file_path)

    def _browse_ts(self) -> None:
        file_path = filedialog.askopenfilename(
            title="TeamSpeak 3 EXE auswählen",
            filetypes=[("Executable", "*.exe")],
        )
        if file_path:
            self.ent_ts.delete(0, "end")
            self.ent_ts.insert(0, file_path)

            detected_plugins = self._detect_ts_plugins_dir(file_path)
            if detected_plugins:
                self.ent_ts_plugins.delete(0, "end")
                self.ent_ts_plugins.insert(0, detected_plugins)

    def _browse_ts_plugins(self) -> None:
        folder_path = filedialog.askdirectory(title="TeamSpeak Pluginordner auswählen")
        if folder_path:
            self.ent_ts_plugins.delete(0, "end")
            self.ent_ts_plugins.insert(0, folder_path)

    def _detect_ts_plugins_dir(self, ts_exe_path: str) -> str:
        """Pluginordner automatisch über teamspeak_control_plugin_win64.dll erkennen."""
        candidates: list[str] = []

        if ts_exe_path:
            candidates.append(os.path.join(os.path.dirname(ts_exe_path), "plugins"))

        appdata = os.environ.get("APPDATA", "")
        candidates.append(os.path.join(appdata, "TS3Client", "plugins"))

        marker_names = (
            "teamspeak_control_plugin_win64.dll",
            "teamspeak_control_plugin_win32.dll",
        )

        for folder in candidates:
            for marker in marker_names:
                if os.path.isfile(os.path.join(folder, marker)):
                    return folder

        # Fallback: erster existierender Kandidat
        for folder in candidates:
            if os.path.isdir(folder):
                return folder
        return ""

    def _auto_detect_paths(self, save: bool = True) -> None:
        steam = find_steam_path()
        arma_path = ""
        if steam:
            arma_path, _ = find_arma3(steam)
            arma_path = arma_path or ""

        ts_path = find_teamspeak_exe() or ""
        plugins_path = self._detect_ts_plugins_dir(ts_path)

        if arma_path:
            self.ent_arma.delete(0, "end")
            self.ent_arma.insert(0, arma_path)
            self._log(f"[OK] Arma 3 erkannt: {arma_path}")
        else:
            self._log("[WARN] Arma 3 EXE konnte nicht automatisch erkannt werden.")

        if ts_path:
            self.ent_ts.delete(0, "end")
            self.ent_ts.insert(0, ts_path)
            self._log(f"[OK] TeamSpeak erkannt: {ts_path}")
        else:
            self._log("[WARN] TeamSpeak EXE konnte nicht automatisch erkannt werden.")

        if plugins_path:
            self.ent_ts_plugins.delete(0, "end")
            self.ent_ts_plugins.insert(0, plugins_path)
            self._log(f"[OK] TeamSpeak Pluginpfad erkannt: {plugins_path}")
        else:
            self._log("[WARN] TeamSpeak Pluginpfad konnte nicht automatisch erkannt werden.")

        if save:
            self._save_paths()

    def _find_workshop_by_arma_exe(self, arma3_exe: str) -> Optional[str]:
        """Workshop-Pfad passend zur ausgewaehlten Arma-Installation finden."""
        game_dir = os.path.normpath(os.path.dirname(arma3_exe))

        steam = find_steam_path()
        if steam:
            for steamapps in find_all_steam_libraries(steam):
                candidate_game_dir = os.path.normpath(os.path.join(steamapps, "common", "Arma 3"))
                if os.path.normcase(candidate_game_dir) == os.path.normcase(game_dir):
                    return os.path.join(steamapps, "workshop", "content", ARMA3_APP_ID)

        marker = f"{os.sep}steamapps{os.sep}common{os.sep}Arma 3"
        lower_game_dir = game_dir.lower()
        marker_index = lower_game_dir.rfind(marker.lower())
        if marker_index != -1:
            steamapps = game_dir[:marker_index] + f"{os.sep}steamapps"
            return os.path.join(steamapps, "workshop", "content", ARMA3_APP_ID)

        return None

    def _find_mod_folder(
        self,
        mod_id: str,
        preferred_workshop_path: Optional[str],
    ) -> Optional[str]:
        """Mod-Ordner ueber alle Steam-Libraries suchen (nicht nur im bevorzugten Workshop-Pfad)."""
        candidates: list[str] = []

        if preferred_workshop_path:
            candidates.append(os.path.join(preferred_workshop_path, mod_id))

        steam = find_steam_path()
        if steam:
            for steamapps in find_all_steam_libraries(steam):
                workshop = os.path.join(steamapps, "workshop", "content", ARMA3_APP_ID, mod_id)
                if workshop not in candidates:
                    candidates.append(workshop)


        for candidate in candidates:
            if os.path.isdir(candidate):
                return candidate
        return None

    def _join_teamspeak(self) -> None:
        url = f"ts3server://{TS3_IP}?port={TS3_PORT}"
        self._log(f"[INFO] Oeffne TeamSpeak: {url}")
        try:
            webbrowser.open(url)
            self._log("[OK] TeamSpeak-Link geoeffnet.")
        except Exception as exc:
            self._log(f"[FEHLER] {exc}")

    def _is_tfar_plugin_installed(self) -> bool:
        """Prueft, ob ein TFAR-Plugin im TS3-Pluginordner vorhanden ist."""
        plugins_dir = self.selected_ts_plugins_dir or self.ent_ts_plugins.get().strip()
        if not plugins_dir:
            plugins_dir = self._detect_ts_plugins_dir(self.selected_ts_exe or self.ent_ts.get().strip())

        self._log(f"[INFO] Pruefe TFAR-Plugin in: {plugins_dir}")

        if not os.path.isdir(plugins_dir):
            self._log("[WARN] TS3 Plugin-Ordner nicht gefunden.")
            return False

        keywords = ("tfar", "task_force_radio", "task force radio")
        try:
            for name in os.listdir(plugins_dir):
                lowered = name.lower()
                if any(keyword in lowered for keyword in keywords):
                    self._log(f"[OK] TFAR-Plugin erkannt: {name}")
                    return True
        except OSError as exc:
            self._log(f"[WARN] Plugin-Ordner konnte nicht gelesen werden: {exc}")
            return False

        self._log("[WARN] Kein TFAR-Plugin gefunden.")
        return False

    def _download_and_start_tfar_plugin_installer(self) -> bool:
        """TFAR Plugin herunterladen und Installer-Datei starten."""
        target_file = os.path.join(tempfile.gettempdir(), "task_force_radio.ts3_plugin")
        self._log(f"[INFO] Lade TFAR-Plugin herunter: {TFAR_PLUGIN_DOWNLOAD_URL}")
        try:
            response = requests.get(TFAR_PLUGIN_DOWNLOAD_URL, timeout=60)
            response.raise_for_status()
            with open(target_file, "wb") as fh:
                fh.write(response.content)
        except Exception as exc:
            self._log(f"[FEHLER] TFAR-Download fehlgeschlagen: {exc}")
            return False

        try:
            os.startfile(target_file)
            self._log(f"[OK] TFAR-Installer gestartet: {target_file}")
            return True
        except Exception as exc:
            self._log(f"[FEHLER] TFAR-Installer konnte nicht gestartet werden: {exc}")
            return False

    def _subscribe_workshop_items(self, mods: list[dict], webapi_key: str) -> tuple[list[dict], list[dict]]:
        """Abonniert Workshop-Items direkt per Steam WebAPI.

        Returns:
            (successful_mods, failed_mods)
        """
        success: list[dict] = []
        failed: list[dict] = []

        for mod in mods:
            mod_id = mod["id"]
            mod_name = mod["name"]
            try:
                response = requests.post(
                    "https://api.steampowered.com/IPublishedFileService/Subscribe/v1/",
                    data={
                        "key": webapi_key,
                        "publishedfileid": mod_id,
                        "list_type": 1,
                        "notify_client": 1,
                    },
                    timeout=20,
                )
                response.raise_for_status()
                success.append(mod)
                self._log(f"[OK] Auto-Abo gesendet: {mod_name} ({mod_id})")
            except Exception as exc:
                failed.append(mod)
                self._log(f"[WARN] Auto-Abo fehlgeschlagen: {mod_name} ({mod_id}) - {exc}")

        return success, failed

    def _parse_version_parts(self, version_text: str) -> tuple[int, ...]:
        """Versionstext in numerische Teile umwandeln, z. B. 1.2.3 -> (1, 2, 3)."""
        parts = re.findall(r"\d+", version_text)
        if not parts:
            return (0,)
        return tuple(int(part) for part in parts)

    def _get_latest_release_info(self) -> tuple[str, Optional[str], str]:
        """Liest die neueste GitHub-Release-Version und das passende EXE-Asset."""
        response = requests.get(GITHUB_API_LATEST_RELEASE_URL, headers=GITHUB_API_HEADERS, timeout=15)
        response.raise_for_status()

        release = response.json()
        remote_version = str(release.get("tag_name") or "").strip()
        if not remote_version:
            raise ValueError("GitHub Release enthaelt kein tag_name")

        release_page_url = str(release.get("html_url") or GITHUB_RELEASES_URL)
        assets = release.get("assets") or []
        asset_url: Optional[str] = None

        for asset_name in LAUNCHER_ASSET_NAMES:
            for asset in assets:
                if asset.get("name") == asset_name and asset.get("browser_download_url"):
                    asset_url = str(asset["browser_download_url"])
                    break
            if asset_url:
                break

        if not asset_url:
            for asset in assets:
                name = str(asset.get("name") or "")
                url = asset.get("browser_download_url")
                if name.lower().endswith(".exe") and url:
                    asset_url = str(url)
                    break

        return remote_version, asset_url, release_page_url

    def _check_launcher_update(self) -> None:
        """GitHub Release prüfen und bei neuer Version ein Update anbieten."""
        try:
            self._log(f"[INFO] Pruefe Launcher-Version (lokal: {LAUNCHER_VERSION})...")
            remote_version, download_url, release_page_url = self._get_latest_release_info()

            local_parts = self._parse_version_parts(LAUNCHER_VERSION)
            remote_parts = self._parse_version_parts(remote_version)

            self._log(f"[INFO] Remote Launcher-Version: {remote_version}")
            if remote_parts > local_parts:
                self._log("[HINWEIS] Neuer Launcher verfuegbar.")
                do_update = self._ask_yes_no_threadsafe(
                    "Launcher Update verfuegbar",
                    f"Eine neue Version ist verfuegbar ({remote_version}). Jetzt Update herunterladen?",
                )
                if do_update:
                    if download_url and self._download_and_apply_update(remote_version, download_url):
                        self._log("[OK] Update geplant. Launcher wird fuer den Austausch beendet...")
                        self.after(0, self._exit_for_update)
                    else:
                        self._log("[WARN] Auto-Update fehlgeschlagen oder kein EXE-Asset gefunden, oeffne Release-Seite als Fallback.")
                        opened = webbrowser.open(release_page_url)
                        if opened:
                            self._log(f"[OK] Release-Seite geoeffnet: {release_page_url}")
                        else:
                            self._log(f"[WARN] Release-Seite konnte nicht automatisch geoeffnet werden: {release_page_url}")
                else:
                    self._log("[INFO] Update uebersprungen.")
            else:
                self._log("[OK] Launcher ist aktuell.")
        except Exception as exc:
            self._log(f"[WARN] Update-Check fehlgeschlagen: {exc}")

    def _exit_for_update(self) -> None:
        """Beendet den Launcher sicher, damit der Updater die EXE austauschen kann."""
        try:
            self.destroy()
        finally:
            os._exit(0)

    def _download_and_apply_update(self, remote_version: str, download_url: str) -> bool:
        """Lädt Update herunter, tauscht EXE aus und startet neu."""
        if not getattr(sys, "frozen", False):
            self._log("[INFO] Auto-Update nur im EXE-Modus verfuegbar.")
            return False

        current_exe = _current_executable_path()
        update_exe = os.path.join(tempfile.gettempdir(), f"launcher_update_{remote_version}.exe")
        updater_cmd = os.path.join(tempfile.gettempdir(), "launcher_apply_update.cmd")
        updater_log = os.path.join(tempfile.gettempdir(), "launcher_apply_update.log")

        try:
            self._log(f"[INFO] Lade Update herunter: {download_url}")
            with requests.get(download_url, timeout=60, stream=True) as response:
                response.raise_for_status()
                with open(update_exe, "wb") as fh:
                    for chunk in response.iter_content(chunk_size=1024 * 128):
                        if chunk:
                            fh.write(chunk)

            current_pid = os.getpid()
            cmd_content = (
                "@echo off\n"
                "setlocal\n"
                f"set PID={current_pid}\n"
                f"set TARGET={current_exe}\n"
                f"set SOURCE={update_exe}\n"
                f"set LOG={updater_log}\n"
                "echo [%date% %time%] Update-Skript gestartet > \"%LOG%\"\n"
                ":waitloop\n"
                "tasklist /FI \"PID eq %PID%\" | findstr /I \"%PID%\" >nul\n"
                "if not errorlevel 1 (\n"
                "  timeout /t 1 /nobreak >nul\n"
                "  goto waitloop\n"
                ")\n"
                "echo [%date% %time%] Zielprozess beendet, starte Austausch >> \"%LOG%\"\n"
                "set RETRIES=0\n"
                ":copyloop\n"
                "copy /Y \"%SOURCE%\" \"%TARGET%\" >nul\n"
                "if errorlevel 1 (\n"
                "  set /a RETRIES+=1\n"
                "  echo [%date% %time%] Copy fehlgeschlagen, Versuch %RETRIES% >> \"%LOG%\"\n"
                "  if %RETRIES% GEQ 10 goto copyfailed\n"
                "  timeout /t 1 /nobreak >nul\n"
                "  goto copyloop\n"
                ")\n"
                "echo [%date% %time%] Copy erfolgreich >> \"%LOG%\"\n"
                "start \"\" \"%TARGET%\"\n"
                "echo [%date% %time%] Launcher neu gestartet >> \"%LOG%\"\n"
                "del /Q \"%SOURCE%\" >nul 2>&1\n"
                "goto end\n"
                ":copyfailed\n"
                "echo [%date% %time%] Update dauerhaft fehlgeschlagen >> \"%LOG%\"\n"
                ":end\n"
                "endlocal\n"
            )

            with open(updater_cmd, "w", encoding="utf-8") as fh:
                fh.write(cmd_content)

            subprocess.Popen(
                ["cmd", "/c", updater_cmd],
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
            )
            return True
        except Exception as exc:
            self._log(f"[WARN] Auto-Update fehlgeschlagen: {exc}")
            return False

    def _list_teamspeak_pids(self) -> set[int]:
        """Aktive TeamSpeak-PIDs aus tasklist lesen."""
        pids: set[int] = set()
        exe_names = ("ts3client_win64.exe", "ts3client_win32.exe")

        for exe_name in exe_names:
            try:
                output = subprocess.check_output(
                    ["tasklist", "/FI", f"IMAGENAME eq {exe_name}", "/FO", "CSV", "/NH"],
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
            except Exception:
                continue

            for line in output.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                if "No tasks are running" in stripped or "Keine Aufgaben" in stripped:
                    continue

                try:
                    row = next(csv.reader([stripped]))
                    pid = int(row[1])
                    pids.add(pid)
                except Exception:
                    continue

        return pids

    def _start_teamspeak_managed(self) -> bool:
        """TeamSpeak mit Prozess-Handle starten, damit wir ihn spaeter schliessen koennen."""
        ts_url = f"ts3server://{TS3_IP}?port={TS3_PORT}"

        if self.ts_proc and self.ts_proc.poll() is None:
            self._log("[INFO] TeamSpeak wurde bereits vom Launcher gestartet.")
            return True

        ts_exe = self.selected_ts_exe if os.path.isfile(self.selected_ts_exe) else None
        if not ts_exe:
            ts_exe = find_teamspeak_exe()
        if not ts_exe:
            self._log("[FEHLER] TeamSpeak 3 ist nicht installiert oder nicht gefunden.")
            install_now = self._ask_yes_no_threadsafe(
                "TeamSpeak 3 fehlt",
                "TeamSpeak 3 wurde nicht gefunden. Moechtest du jetzt installieren?",
            )
            if install_now:
                webbrowser.open(TS3_DOWNLOAD_URL)
                self._log(f"[INFO] TeamSpeak Downloadseite geoeffnet: {TS3_DOWNLOAD_URL}")
            self.ts_proc = None
            return False

        if not self._is_tfar_plugin_installed():
            install_plugin = self._ask_yes_no_threadsafe(
                "TFAR Plugin fehlt",
                "TFAR Plugin wurde nicht gefunden. Moechtest du Plugin herunterladen und installieren?",
            )
            if install_plugin:
                self._download_and_start_tfar_plugin_installer()
            else:
                self._log("[INFO] TFAR-Installation uebersprungen.")

        # Eigene Instanz starten, damit der Launcher sie wieder schliessen kann.
        self.ts_url_pid = None
        args_no_sound = [ts_exe, "-nosingleinstance", "-nosound", ts_url]
        args_fallback = [ts_exe, "-nosingleinstance", ts_url]

        try:
            self._log("[INFO] Starte TeamSpeak mit deaktivierten Sounds...")
            self.ts_proc = subprocess.Popen(args_no_sound, cwd=os.path.dirname(ts_exe))
            # Bei unbekannten Parametern beendet sich TS ggf. sofort.
            time.sleep(1.2)
            if self.ts_proc.poll() is not None:
                self._log("[WARN] TeamSpeak hat '-nosound' nicht akzeptiert. Starte ohne Sound-Flag neu.")
                self.ts_proc = subprocess.Popen(args_fallback, cwd=os.path.dirname(ts_exe))
        except OSError as exc:
            if getattr(exc, "winerror", None) == 740:
                self._log("[WARN] TeamSpeak verlangt erhoehte Rechte (WinError 740).")
                self._log("[HINWEIS] Starte TeamSpeak jetzt explizit erhoeht (runas).")

                params_no_sound = f'-nosingleinstance -nosound "{ts_url}"'
                params_fallback = f'-nosingleinstance "{ts_url}"'

                before = self._list_teamspeak_pids()
                rc = ctypes.windll.shell32.ShellExecuteW(
                    None,
                    "runas",
                    ts_exe,
                    params_no_sound,
                    os.path.dirname(ts_exe),
                    1,
                )

                if rc <= 32:
                    self._log("[WARN] Erhoehter Start mit -nosound fehlgeschlagen. Starte ohne Sound-Flag neu.")
                    rc = ctypes.windll.shell32.ShellExecuteW(
                        None,
                        "runas",
                        ts_exe,
                        params_fallback,
                        os.path.dirname(ts_exe),
                        1,
                    )

                if rc > 32:
                    self._log("[OK] TeamSpeak erhoeht gestartet.")
                    time.sleep(1.5)
                    after = self._list_teamspeak_pids()
                    new_pids = sorted(after - before)
                    if new_pids:
                        self.ts_url_pid = new_pids[-1]
                        self._log(f"[INFO] TeamSpeak PID fuer Auto-Beenden gemerkt: {self.ts_url_pid}")
                    else:
                        self._log("[WARN] Keine neue TeamSpeak-PID erkannt. Laufende TS-Instanz wird nicht automatisch beendet.")
                    self.ts_proc = None
                    return True

                self._log("[WARN] Erhoehter TeamSpeak-Start fehlgeschlagen. Fallback auf ts3server://-Start.")
                before = self._list_teamspeak_pids()
                if webbrowser.open(ts_url):
                    self._log("[OK] TeamSpeak per Protokoll-URL gestartet.")
                    time.sleep(1.5)
                    after = self._list_teamspeak_pids()
                    new_pids = sorted(after - before)
                    if new_pids:
                        self.ts_url_pid = new_pids[-1]
                        self._log(f"[INFO] TeamSpeak PID fuer Auto-Beenden gemerkt: {self.ts_url_pid}")
                    else:
                        self._log("[WARN] Keine neue TeamSpeak-PID erkannt. Laufende TS-Instanz wird nicht automatisch beendet.")
                    self.ts_proc = None
                    return True
                self._log("[FEHLER] TeamSpeak konnte auch per Protokoll-URL nicht gestartet werden.")
            else:
                self._log(f"[FEHLER] TeamSpeak konnte nicht gestartet werden: {exc}")
            self.ts_proc = None
            return False
        self._log(f"[OK] TeamSpeak gestartet (PID: {self.ts_proc.pid})")
        return True

    def _start_launch(self) -> None:
        self.selected_arma_exe = self.ent_arma.get().strip()
        self.selected_ts_exe = self.ent_ts.get().strip()
        self.selected_ts_plugins_dir = self.ent_ts_plugins.get().strip()
        self.selected_steam_webapi_key = self.ent_steam_webapi_key.get().strip()
        self.cfg["arma3_exe"] = self.selected_arma_exe
        self.cfg["teamspeak_exe"] = self.selected_ts_exe
        self.cfg["teamspeak_plugins_dir"] = self.selected_ts_plugins_dir
        self.cfg["steam_webapi_key"] = self.selected_steam_webapi_key
        save_config(self.cfg)
        self.launch_btn.configure(state="disabled")
        self._set_status("Starte...", "#ff9800")
        threading.Thread(target=self._launch_worker, daemon=True).start()

    def _launch_worker(self) -> None:
        arma_started = False
        try:
            self._log("[INFO] Pruefe Arma 3 Pfad...")
            if self.selected_arma_exe and os.path.isfile(self.selected_arma_exe):
                arma3_exe = self.selected_arma_exe
                workshop_path = self._find_workshop_by_arma_exe(arma3_exe)
                self._log("[OK] Arma 3 aus manuellem Pfad.")
            else:
                steam = find_steam_path()
                if not steam:
                    self._log("[FEHLER] Steam nicht gefunden und kein gueltiger Arma-Pfad gesetzt!")
                    self._set_status("Fehler", "#f44336")
                    return

                arma3_exe, workshop_path = find_arma3(steam)
                if not arma3_exe:
                    self._log("[FEHLER] Arma 3 nicht gefunden!")
                    self._set_status("Fehler", "#f44336")
                    return
                self.after(0, lambda p=arma3_exe: (self.ent_arma.delete(0, "end"), self.ent_arma.insert(0, p)))
                self.cfg["arma3_exe"] = arma3_exe
                save_config(self.cfg)
                self._log("[OK] Arma 3 automatisch erkannt und gespeichert.")

            self._log(f"[OK] Arma 3: {arma3_exe}")

            if not workshop_path or not os.path.isdir(workshop_path):
                self._log("[FEHLER] Workshop-Ordner konnte fuer diese Arma-Installation nicht gefunden werden.")
                self._set_status("Workshop fehlt", "#f44336")
                return

            self._log("[INFO] Lade Modlist...")
            self._set_status("Lade Modlist...", "#ff9800")
            try:
                resp = requests.get(PRESET_URL, timeout=20)
                resp.raise_for_status()
                self._log(f"[OK] Modlist geladen ({len(resp.text):,} Bytes)")
            except requests.RequestException as exc:
                self._log(f"[FEHLER] Download fehlgeschlagen: {exc}")
                self._set_status("Fehler", "#f44336")
                return

            mods = parse_preset(resp.text)
            if not mods:
                self._log("[FEHLER] Keine Mods in der Modlist gefunden!")
                self._set_status("Fehler", "#f44336")
                return
            self._log(f"[OK] {len(mods)} Mod(s) in der Liste")

            self._set_status("Pruefe Mods...", "#ff9800")
            mod_paths: list[str] = []
            installed_mods: list[dict] = []
            missing: list[dict] = []

            for mod in mods:
                folder = self._find_mod_folder(mod["id"], workshop_path)
                if folder and os.path.isdir(folder):
                    # Prüfen ob addons/-Unterordner existiert (leere Ordner crashen Arma)
                    has_addons = os.path.isdir(os.path.join(folder, "addons"))
                    if not has_addons:
                        self._log(f"  WARN {mod['name']} — kein 'addons' Unterordner! (unvollständig heruntergeladen?)")
                    mod_paths.append(folder)
                    installed_mods.append({"name": mod["name"], "id": mod["id"], "path": folder})
                    status = "OK" if has_addons else "WARN"
                    self._log(f"  {status} {mod['name']}")
                else:
                    missing.append({"name": mod["name"], "id": mod["id"]})
                    self._log(f"  FEHLT: {mod['name']} ({mod['id']})")

            if missing:
                self._log(f"\n[FEHLER] {len(missing)} Mod(s) fehlen! Start abgebrochen.")
                self._log("[HINWEIS] Fehlende Mods zuerst im Arma 3 Launcher abonnieren/synchronisieren.")
                for mod in missing:
                    self._log(f"  FEHLT: {mod['name']} ({mod['id']})")

                self._set_status("Fehlende Mods", "#f44336")
                self._log("[INFO] Starte Abo-Assistent (ein Mod nach dem anderen)...")

                webapi_key = self.selected_steam_webapi_key or self.cfg.get("steam_webapi_key", "")
                if webapi_key:
                    auto_subscribe = self._ask_yes_no_threadsafe(
                        "Mods automatisch abonnieren",
                        f"{len(missing)} Mod(s) fehlen. Soll der Launcher zuerst versuchen, sie automatisch per Steam WebAPI zu abonnieren?",
                    )
                    if auto_subscribe:
                        self._log("[INFO] Versuche automatische Workshop-Abos...")
                        _, failed_auto = self._subscribe_workshop_items(missing, webapi_key)
                        if not failed_auto:
                            self._log("[OK] Alle fehlenden Mods wurden zum Abonnieren an Steam uebergeben.")
                            self._log("[INFO] Warte kurz auf Steam Sync und klicke dann erneut auf SPIEL STARTEN.")
                            return
                        missing = failed_auto
                        self._log("[WARN] Ein Teil der Mods konnte nicht automatisch abonniert werden. Fallback auf manuelle Workshop-Seiten.")
                else:
                    self._log("[INFO] Kein Steam WebAPI Key gesetzt. Auto-Abo nicht verfuegbar.")

                for mod in missing:
                    ask = self._ask_yes_no_threadsafe(
                        "Mod abonnieren",
                        f"Moechtest du {mod['name']} abonnieren?",
                    )
                    if ask:
                        self._open_missing_mods_in_steam([mod])
                        self._log(f"[INFO] Bitte Mod in Steam abonnieren: {mod['name']} ({mod['id']})")
                    else:
                        self._log(f"[INFO] Uebersprungen: {mod['name']} ({mod['id']})")

                self._log("[INFO] Nach dem Abonnieren bitte erneut auf SPIEL STARTEN klicken.")
                return

            invalid_addons = [
                mod_path for mod_path in mod_paths
                if not os.path.isdir(os.path.join(mod_path, "addons"))
            ]
            if invalid_addons:
                self._log(f"\n[FEHLER] {len(invalid_addons)} Mod(s) ohne addons-Ordner gefunden! Start abgebrochen.")
                self._log("[HINWEIS] Diese Mods sind vermutlich unvollstaendig heruntergeladen und koennen Crashes verursachen.")
                for bad_path in invalid_addons:
                    self._log(f"  KAPUTT: {bad_path}")
                self._set_status("Defekte Mods", "#f44336")
                return

            if not mod_paths:
                self._log("[FEHLER] Keine Mods installiert. Zuerst Mods abonnieren!")
                self._set_status("Fehler", "#f44336")
                return

            args = [
                arma3_exe,
                f"-mod={';'.join(mod_paths)}",
                f"-connect={SERVER_IP}",
                f"-port={SERVER_PORT}",
                f"-password={SERVER_PW}",
            ]

            self._log(
                f"\n[CMD] {arma3_exe}\n"
                f"      -mod=({len(mod_paths)} Mods)\n"
                f"      -connect={SERVER_IP} -port={SERVER_PORT}\n"
            )
            # Jeden Mod-Pfad einzeln ausgeben damit man sieht was übergeben wird
            for i, p in enumerate(mod_paths, 1):
                self._log(f"      [{i:02d}] {p}")

            self._log("\n[INFO] Starte TeamSpeak 3...")
            ts_started = self._start_teamspeak_managed()
            if not ts_started:
                self._set_status("TeamSpeak fehlt", "#f44336")
                self._log("[INFO] Start abgebrochen bis TeamSpeak installiert ist.")
                return

            self._log("[INFO] Starte Arma 3...")
            try:
                proc = subprocess.Popen(args, cwd=os.path.dirname(arma3_exe))
            except OSError as exc:
                if getattr(exc, "winerror", None) == 740:
                    self._log("[FEHLER] Arma 3 verlangt erhoehte Rechte (WinError 740).")
                    self._log("[HINWEIS] Entferne bei Arma 3 die Option 'Als Administrator ausfuehren' in den Kompatibilitaetseinstellungen oder starte den Launcher als Admin.")
                else:
                    self._log(f"[FEHLER] Arma 3 konnte nicht gestartet werden: {exc}")
                self._set_status("Start fehlgeschlagen", "#f44336")
                return
            arma_started = True
            self._log("[OK] Arma 3 gestartet! PID: " + str(proc.pid))
            self._set_status("Arma 3 laeuft...", "#4caf50")

            # Prozess im Hintergrund beobachten
            threading.Thread(target=self._watch_process, args=(proc,), daemon=True).start()

        except Exception as exc:
            self._log(f"[FEHLER] Unerwarteter Fehler: {exc}")
            self._set_status("Fehler", "#f44336")
            if self.ts_proc and self.ts_proc.poll() is None:
                try:
                    self.ts_proc.terminate()
                except Exception:
                    pass
                self.ts_proc = None
        finally:
            if not arma_started:
                self.after(0, lambda: self.launch_btn.configure(state="normal"))

    def _watch_process(self, proc: subprocess.Popen) -> None:
        """Wartet auf Arma 3 und liest danach den neuesten RPT-Log."""
        exit_code = proc.wait()
        self._log(f"\n[INFO] Arma 3 beendet. Exit-Code: {exit_code}")

        # TeamSpeak-Instanz, die vom Launcher gestartet wurde, sauber beenden.
        if self.ts_proc and self.ts_proc.poll() is None:
            self._log("[INFO] Beende TeamSpeak 3...")
            try:
                self.ts_proc.terminate()
                self.ts_proc.wait(timeout=8)
                self._log("[OK] TeamSpeak 3 beendet.")
            except Exception:
                try:
                    self.ts_proc.kill()
                    self._log("[WARN] TeamSpeak 3 musste hart beendet werden.")
                except Exception as exc:
                    self._log(f"[WARN] TeamSpeak 3 konnte nicht beendet werden: {exc}")
            finally:
                self.ts_proc = None
        elif self.ts_url_pid:
            self._log(f"[INFO] Beende TeamSpeak 3 (PID {self.ts_url_pid})...")
            try:
                result = subprocess.run(
                    ["taskkill", "/PID", str(self.ts_url_pid), "/T"],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    self._log("[OK] TeamSpeak 3 beendet.")
                else:
                    result_force = subprocess.run(
                        ["taskkill", "/PID", str(self.ts_url_pid), "/T", "/F"],
                        capture_output=True,
                        text=True,
                    )
                    if result_force.returncode == 0:
                        self._log("[WARN] TeamSpeak 3 musste hart beendet werden.")
                    else:
                        self._log("[WARN] TeamSpeak 3 konnte nicht automatisch beendet werden.")
            except Exception as exc:
                self._log(f"[WARN] TeamSpeak 3 konnte nicht beendet werden: {exc}")
            finally:
                self.ts_url_pid = None

        if exit_code != 0:
            self._set_status(f"Arma 3 Crash (Code {exit_code})", "#f44336")
        else:
            self._set_status("Arma 3 beendet", "#546e7a")

        # Neuesten RPT-Log lesen und letzte Zeilen anzeigen
        self._read_rpt_log()
        self.after(0, lambda: self.launch_btn.configure(state="normal"))

    def _read_rpt_log(self) -> None:
        """Liest den neuesten Arma 3 RPT-Log und zeigt die letzten Zeilen."""
        log_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Arma 3")
        if not os.path.isdir(log_dir):
            self._log("[WARN] Arma3 Log-Ordner nicht gefunden.")
            return

        rpt_files = glob.glob(os.path.join(log_dir, "*.rpt"))
        if not rpt_files:
            self._log("[WARN] Keine .rpt Log-Datei gefunden.")
            return

        newest = max(rpt_files, key=os.path.getmtime)
        self._log(f"\n[LOG] Neuester RPT-Log: {newest}")
        self._log("[LOG] --- Letzte 40 Zeilen ---")
        try:
            with open(newest, "r", encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
            for line in lines[-40:]:
                stripped = line.rstrip()
                if stripped:
                    self._log(stripped)
        except OSError as exc:
            self._log(f"[WARN] Log konnte nicht gelesen werden: {exc}")
        self._log("[LOG] --- Ende ---")


if __name__ == "__main__":
    if not ensure_admin_rights():
        raise SystemExit(0)
    if not _install_launcher_if_needed():
        raise SystemExit(0)
    app = LauncherApp()
    app.mainloop()