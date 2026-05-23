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
import socket
import struct
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

try:
    import pywinstyles
except Exception:
    pywinstyles = None

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
DISCORD_URL = "https://discord.gg/ageofclones"
GITHUB_REPO = "ltsammy/strikeplatoon"
GITHUB_API_LATEST_RELEASE_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"
LAUNCHER_ASSET_NAMES = ("launcher.exe", "104Launcher.exe")
GITHUB_API_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "104Launcher",
}
ARMA3_APP_ID  = "107410"
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

# PyInstaller onefile: Assets liegen zur Laufzeit in _MEIPASS.
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
    """Launcher benoetigt keine globalen Adminrechte."""
    return True


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
    """Installiert die EXE benutzerbezogen und erstellt optional Verknuepfungen.

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
            "Launcher wurde installiert und wird jetzt aus dem Benutzerprofil gestartet.",
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
        self.background_image = None
        self._background_source_image = None
        self._bg_resize_job = None
        self._transparency_targets: list[tuple[object, Optional[float]]] = []
        self.transparency_enabled = (
            sys.platform.startswith("win")
            and pywinstyles is not None
            and not getattr(sys, "frozen", False)
        )
        self.paths_visible = False
        self.selected_arma_exe = ""
        self.selected_ts_exe = ""
        self.selected_ts_plugins_dir = ""
        self.server_players_value: Optional[str] = None
        self.mod_count_value: Optional[str] = None

        self.title("Strike Platoon | Arma 3 Launcher")
        self._set_window_icon()
        self._configure_window_size_from_background()
        self.resizable(True, True)
        self._build_ui()
        self.bind("<Configure>", self._on_window_resize)
        self.after(250, self._reapply_transparency_targets)
        self.after(900, self._reapply_transparency_targets)
        self.after(800, lambda: threading.Thread(target=self._check_launcher_update, daemon=True).start())

    def _resolve_background_image_path(self) -> Optional[str]:
        candidates = [
            BACKGROUND_IMAGE_PATH,
            os.path.join(os.path.dirname(APP_BASE_DIR), "background.jpg"),
            os.path.join(os.getcwd(), "background.jpg"),
        ]
        for candidate in candidates:
            if os.path.isfile(candidate):
                return candidate
        return None

    def _configure_window_size_from_background(self) -> None:
        bg_path = self._resolve_background_image_path()
        if not bg_path:
            self.geometry("980x760")
            self.minsize(820, 600)
            return

        try:
            with Image.open(bg_path) as img:
                img_w, img_h = img.size
        except Exception:
            self.geometry("980x760")
            self.minsize(820, 600)
            return

        screen_w = max(self.winfo_screenwidth(), 1280)
        screen_h = max(self.winfo_screenheight(), 720)
        scale = min((screen_w * 0.64) / img_w, (screen_h * 0.72) / img_h)
        scale = max(0.45, min(scale, 1.0))

        target_w = max(900, int(img_w * scale))
        target_h = max(620, int(img_h * scale))
        self.geometry(f"{target_w}x{target_h}")
        self.minsize(max(820, int(target_w * 0.78)), max(560, int(target_h * 0.78)))

    def _set_window_icon(self) -> None:
        """Setzt das Fenster-Icon (Titelleiste/Taskbar) auf das Projektlogo."""
        try:
            if os.path.isfile(LOGO_ICO_PATH):
                self.iconbitmap(LOGO_ICO_PATH)
        except Exception:
            pass

    def _apply_widget_transparency(self, widget, opacity: Optional[float] = None) -> None:
        if not self.transparency_enabled:
            return

        if self._set_widget_transparency(widget, opacity):
            self._transparency_targets.append((widget, opacity))

    def _set_widget_transparency(self, widget, opacity: Optional[float] = None) -> bool:
        if not self.transparency_enabled:
            return False

        chroma_key = "#000001"
        previous_bg = None
        try:
            previous_bg = widget.cget("bg_color")
        except Exception:
            previous_bg = None

        try:
            widget.configure(bg_color=chroma_key)
        except Exception:
            return False

        try:
            if opacity is None:
                pywinstyles.set_opacity(widget, color=chroma_key)
            else:
                pywinstyles.set_opacity(widget, value=opacity, color=chroma_key)
            return True
        except Exception:
            if previous_bg is not None:
                try:
                    widget.configure(bg_color=previous_bg)
                except Exception:
                    pass
            return False

    def _reapply_transparency_targets(self) -> None:
        if not self.transparency_enabled:
            return

        for widget, opacity in list(self._transparency_targets):
            try:
                if widget.winfo_exists():
                    self._set_widget_transparency(widget, opacity)
            except Exception:
                continue

    def _build_ui(self) -> None:
        self.configure(fg_color="#102437")

        self.bg_label = ctk.CTkLabel(self, text="")
        self.bg_label.place(x=0, y=0, relwidth=1, relheight=1)
        self._load_background_image()

        if os.path.isfile(LOGO_PNG_PATH):
            try:
                logo_pil = Image.open(LOGO_PNG_PATH)
                self.logo_image = ctk.CTkImage(light_image=logo_pil, dark_image=logo_pil, size=(260, 260))
                self.logo_label = ctk.CTkLabel(self, image=self.logo_image, text="", fg_color="transparent", bg_color="transparent")
                self.logo_label.place(relx=0.5, rely=0.28, anchor="center")
                self._apply_widget_transparency(self.logo_label)
            except Exception:
                pass

        self.launch_btn = ctk.CTkButton(
            self,
            text="Server betreten",
            width=300,
            height=60,
            corner_radius=999,
            border_width=1,
            border_color="#d1e5c3",
            font=ctk.CTkFont(size=22, weight="bold"),
            fg_color="#2f8f5f",
            bg_color="transparent",
            hover_color="#236f4a",
            command=self._start_server_launch,
        )
        self.launch_btn.place(relx=0.5, rely=0.50, anchor="center")
        self._apply_widget_transparency(self.launch_btn)

        self.singleplayer_btn = ctk.CTkButton(
            self,
            text="Singleplayer starten",
            width=220,
            height=34,
            corner_radius=999,
            border_width=1,
            border_color="#9cb2c8",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="#2a3f56",
            bg_color="transparent",
            hover_color="#35526f",
            command=self._start_singleplayer_launch,
        )
        self.singleplayer_btn.place(relx=0.5, rely=0.57, anchor="center")
        self._apply_widget_transparency(self.singleplayer_btn)

        self.status_lbl = ctk.CTkLabel(
            self,
            text="Bereit",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#b4cadf",
            fg_color="transparent",
            bg_color="transparent",
        )
        self.status_lbl.place(relx=0.5, rely=0.64, anchor="center")
        self._apply_widget_transparency(self.status_lbl)

        self.path_frame = ctk.CTkFrame(
            self,
            fg_color="#102437",
            corner_radius=0,
            border_width=1,
            border_color="#3d5c7d",
        )
        self.path_frame.pack(fill="x", padx=24, pady=(0, 10))

        ctk.CTkLabel(self.path_frame, text="Arma 3 EXE", width=130, anchor="w", text_color="#d7e3f0").grid(
            row=0, column=0, padx=(14, 8), pady=(12, 6), sticky="w"
        )
        self.ent_arma = ctk.CTkEntry(self.path_frame, fg_color="#18324a", border_color="#6f8baa")
        self.ent_arma.grid(row=0, column=1, padx=6, pady=(12, 6), sticky="ew")

        ctk.CTkButton(
            self.path_frame, text="...", width=36, command=self._browse_arma,
            fg_color="#2d4e74", hover_color="#3e6694", border_width=1, border_color="#6a859f"
        ).grid(row=0, column=2, padx=(6, 8), pady=(12, 6))

        ctk.CTkLabel(self.path_frame, text="TS3 EXE", width=130, anchor="w", text_color="#d7e3f0").grid(
            row=1, column=0, padx=(14, 8), pady=(0, 6), sticky="w"
        )
        self.ent_ts = ctk.CTkEntry(self.path_frame, fg_color="#18324a", border_color="#6f8baa")
        self.ent_ts.grid(row=1, column=1, padx=6, pady=(0, 6), sticky="ew")

        ctk.CTkButton(
            self.path_frame, text="...", width=36, command=self._browse_ts,
            fg_color="#2d4e74", hover_color="#3e6694", border_width=1, border_color="#6a859f"
        ).grid(row=1, column=2, padx=(6, 8), pady=(0, 6))

        ctk.CTkLabel(self.path_frame, text="TS3 Pluginpfad", width=130, anchor="w", text_color="#d7e3f0").grid(
            row=2, column=0, padx=(14, 8), pady=(0, 12), sticky="w"
        )
        self.ent_ts_plugins = ctk.CTkEntry(self.path_frame, fg_color="#18324a", border_color="#6f8baa")
        self.ent_ts_plugins.grid(row=2, column=1, padx=6, pady=(0, 12), sticky="ew")

        ctk.CTkButton(
            self.path_frame, text="...", width=36, command=self._browse_ts_plugins,
            fg_color="#2d4e74", hover_color="#3e6694", border_width=1, border_color="#6a859f"
        ).grid(row=2, column=2, padx=(6, 8), pady=(0, 12))

        ctk.CTkButton(
            self.path_frame,
            text="Auto erkennen",
            width=132,
            command=self._auto_detect_paths,
            fg_color="#315d40",
            hover_color="#3f7752",
            border_width=1,
            border_color="#8fb39b",
        ).grid(row=0, column=3, padx=(6, 14), pady=(12, 6))
        ctk.CTkButton(
            self.path_frame,
            text="Pfade speichern",
            width=132,
            command=self._save_paths,
            fg_color="#315d40",
            hover_color="#3f7752",
            border_width=1,
            border_color="#8fb39b",
        ).grid(row=1, column=3, padx=(6, 14), pady=(0, 6))
        self.path_frame.columnconfigure(1, weight=1)

        bottom_bar = ctk.CTkFrame(
            self,
            fg_color="#0f2238",
            corner_radius=0,
            border_width=1,
            border_color="#3a5678",
        )
        self.bottom_bar = bottom_bar
        bottom_bar.pack(side="bottom", fill="x", padx=24, pady=(0, 12))
        for idx in range(4):
            bottom_bar.grid_columnconfigure(idx, weight=1)

        self.open_arma_folder_btn = ctk.CTkButton(
            bottom_bar,
            text="Arma 3 Ordner öffnen",
            height=42,
            corner_radius=12,
            fg_color="#27456b",
            hover_color="#355a87",
            border_width=1,
            border_color="#6a859f",
            command=self._open_arma_folder,
        )
        self.open_arma_folder_btn.grid(row=0, column=0, padx=(10, 6), pady=10, sticky="ew")

        self.toggle_log_btn = ctk.CTkButton(
            bottom_bar,
            text="Launcher Logs",
            height=42,
            corner_radius=12,
            fg_color="#5a4826",
            hover_color="#6d5a32",
            border_width=1,
            border_color="#af9e7b",
            command=self._toggle_log_visibility,
        )
        self.toggle_log_btn.grid(row=0, column=1, padx=6, pady=10, sticky="ew")

        self.discord_btn = ctk.CTkButton(
            bottom_bar,
            text="Discord",
            height=42,
            corner_radius=12,
            fg_color="#28547c",
            hover_color="#376a9a",
            border_width=1,
            border_color="#7d9ebf",
            command=lambda: webbrowser.open(DISCORD_URL),
        )
        self.discord_btn.grid(row=0, column=2, padx=6, pady=10, sticky="ew")

        self.path_toggle_btn = ctk.CTkButton(
            bottom_bar,
            text="Pfade anpassen",
            height=42,
            corner_radius=12,
            fg_color="#2f5d41",
            hover_color="#3e7653",
            border_width=1,
            border_color="#88a794",
            command=self._toggle_paths_visibility,
        )
        self.path_toggle_btn.grid(row=0, column=3, padx=(6, 10), pady=10, sticky="ew")

        self.log_box = ctk.CTkTextbox(
            self,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color="#102437",
            border_color="#3d5c7d",
            border_width=1,
            corner_radius=0,
            height=220,
        )
        self.log_box.configure(state="disabled")

        self.path_frame.pack_forget()
        self._load_paths_into_ui()

    def _load_background_image(self) -> None:
        bg_path = self._resolve_background_image_path()
        if not bg_path:
            return

        try:
            self._background_source_image = Image.open(bg_path)
        except Exception:
            self._background_source_image = None
            return

        self._update_background_image()

    def _on_window_resize(self, event) -> None:
        if event.widget is not self:
            return
        if self._bg_resize_job is not None:
            self.after_cancel(self._bg_resize_job)
        self._bg_resize_job = self.after(80, self._update_background_image)

    def _update_background_image(self) -> None:
        self._bg_resize_job = None
        if self._background_source_image is None:
            return

        width = max(self.winfo_width(), 1)
        height = max(self.winfo_height(), 1)

        img_ratio = self._background_source_image.width / max(self._background_source_image.height, 1)
        window_ratio = width / max(height, 1)

        if window_ratio > img_ratio:
            scaled_width = width
            scaled_height = int(width / img_ratio)
        else:
            scaled_height = height
            scaled_width = int(height * img_ratio)

        resampling_module = getattr(Image, "Resampling", Image)
        resized = self._background_source_image.resize((scaled_width, scaled_height), resampling_module.LANCZOS)
        left = max((scaled_width - width) // 2, 0)
        top = max((scaled_height - height) // 2, 0)
        cropped = resized.crop((left, top, left + width, top + height))
        self.background_image = ctk.CTkImage(light_image=cropped, dark_image=cropped, size=(width, height))
        self.bg_label.configure(image=self.background_image)

    def _toggle_paths_visibility(self) -> None:
        self.paths_visible = not self.paths_visible
        if self.paths_visible:
            self.path_frame.pack(side="bottom", fill="x", padx=24, pady=(0, 10))
            self.path_frame.lift(self.bottom_bar)
            self.path_toggle_btn.configure(text="Pfade ausblenden")
        else:
            self.path_frame.pack_forget()
            self.path_toggle_btn.configure(text="Pfade anpassen")

    def _schedule_info_refresh(self, initial_delay_ms: int = 60000) -> None:
        self.after(initial_delay_ms, self._refresh_info_async)

    def _refresh_info_async(self) -> None:
        threading.Thread(target=self._refresh_info_worker, daemon=True).start()
        self._schedule_info_refresh()

    def _refresh_info_worker(self) -> None:
        players_text = "Nicht erreichbar"
        mod_count_text = "Nicht erreichbar"

        try:
            players_text = self._fetch_server_player_text()
        except Exception as exc:
            self._log(f"[WARN] Serverstatus konnte nicht geladen werden: {exc}")

        try:
            response = requests.get(PRESET_URL, timeout=15)
            response.raise_for_status()
            mod_count_text = str(len(parse_preset(response.text)))
        except Exception as exc:
            self._log(f"[WARN] Modliste konnte nicht geladen werden: {exc}")

        def _apply() -> None:
            self.server_value_lbl.configure(text=players_text)
            self.mod_count_lbl.configure(text=mod_count_text)

        self.after(0, _apply)

    def _fetch_server_player_text(self) -> str:
        for port in SERVER_QUERY_PORTS:
            stats = self._query_a2s_info(SERVER_IP, port)
            if stats is not None:
                players, max_players = stats
                return f"{players}/{max_players}"
        return "Offline"

    def _query_a2s_info(self, host: str, port: int) -> Optional[tuple[int, int]]:
        request = b"\xFF\xFF\xFF\xFFTSource Engine Query\x00"

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(2.5)
                sock.sendto(request, (host, port))
                response, _ = sock.recvfrom(4096)
        except (TimeoutError, OSError):
            return None

        if len(response) < 6 or response[:4] != b"\xFF\xFF\xFF\xFF":
            return None

        if response[4] == 0x41:
            challenge = response[5:9]
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    sock.settimeout(2.5)
                    sock.sendto(request + challenge, (host, port))
                    response, _ = sock.recvfrom(4096)
            except (TimeoutError, OSError):
                return None

        if len(response) < 6 or response[4] != 0x49:
            return None

        index = 5
        index += 1  # protocol
        for _ in range(4):
            end = response.find(b"\x00", index)
            if end == -1:
                return None
            index = end + 1

        if index + 6 > len(response):
            return None

        index += 2  # app id
        players = response[index]
        max_players = response[index + 1]
        return int(players), int(max_players)

    def _toggle_log_visibility(self) -> None:
        self.log_visible = not self.log_visible
        if self.log_visible:
            self.log_box.pack(side="bottom", fill="x", padx=24, pady=(0, 16))
            self.log_box.configure(height=220)
            self.log_box.lift(self.bottom_bar)
            self.toggle_log_btn.configure(text="Logs ausblenden")
        else:
            self.log_box.pack_forget()
            self.toggle_log_btn.configure(text="Launcher Logs")

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

    def _open_arma_folder(self) -> None:
        arma_exe = self.ent_arma.get().strip()
        if not arma_exe:
            self._log("[WARN] Kein Arma 3 Pfad gesetzt. Bitte erst unter 'Pfade anpassen' eintragen.")
            return

        arma_dir = os.path.dirname(arma_exe)
        if os.path.isdir(arma_dir):
            os.startfile(arma_dir)
            self._log(f"[INFO] Arma 3 Ordner geoeffnet: {arma_dir}")
        else:
            self._log(f"[WARN] Arma 3 Ordner nicht gefunden: {arma_dir}")

    def _load_paths_into_ui(self) -> None:
        arma_cfg = self.cfg.get("arma3_exe", "")
        ts_cfg = self.cfg.get("teamspeak_exe", "")
        plugins_cfg = self.cfg.get("teamspeak_plugins_dir", "")

        if arma_cfg and os.path.isfile(arma_cfg):
            self.ent_arma.delete(0, "end")
            self.ent_arma.insert(0, arma_cfg)

        if ts_cfg and os.path.isfile(ts_cfg):
            self.ent_ts.delete(0, "end")
            self.ent_ts.insert(0, ts_cfg)

        if plugins_cfg and os.path.isdir(plugins_cfg):
            self.ent_ts_plugins.delete(0, "end")
            self.ent_ts_plugins.insert(0, plugins_cfg)

        if not self.ent_arma.get().strip() or not self.ent_ts.get().strip() or not self.ent_ts_plugins.get().strip():
            self._auto_detect_paths(save=False)

    def _save_paths(self) -> None:
        arma_path = self.ent_arma.get().strip()
        ts_path = self.ent_ts.get().strip()
        ts_plugins_path = self.ent_ts_plugins.get().strip()
        self.cfg["arma3_exe"] = arma_path
        self.cfg["teamspeak_exe"] = ts_path
        self.cfg["teamspeak_plugins_dir"] = ts_plugins_path
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
        updater_script = os.path.join(tempfile.gettempdir(), "launcher_apply_update.ps1")
        updater_log = os.path.join(tempfile.gettempdir(), "launcher_apply_update.log")

        try:
            self._log(f"[INFO] Lade Update herunter: {download_url}")
            with requests.get(download_url, timeout=60, stream=True) as response:
                response.raise_for_status()
                expected_size = int(response.headers.get("content-length") or 0)
                downloaded_size = 0
                with open(update_exe, "wb") as fh:
                    for chunk in response.iter_content(chunk_size=1024 * 128):
                        if chunk:
                            fh.write(chunk)
                            downloaded_size += len(chunk)

            if expected_size and downloaded_size != expected_size:
                raise RuntimeError(
                    f"Update-Datei unvollstaendig: {downloaded_size} von {expected_size} Bytes geladen"
                )

            current_pid = os.getpid()
            def _ps_escape(value: str) -> str:
                return value.replace("'", "''")

            script_content = (
                f"$pidToWait = {current_pid}\n"
                f"$target = '{_ps_escape(current_exe)}'\n"
                f"$source = '{_ps_escape(update_exe)}'\n"
                f"$log = '{_ps_escape(updater_log)}'\n"
                "$backup = $target + '.bak'\n"
                "$Host.UI.RawUI.WindowTitle = '104 Launcher Update'\n"
                "function Write-Log($message) {\n"
                "    Add-Content -Path $log -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' ' + $message)\n"
                "}\n"
                "function Show-Step($percent, $status) {\n"
                "    Write-Progress -Activity '104 Launcher Update' -Status $status -PercentComplete $percent\n"
                "    Write-Host ('[{0,3}%] {1}' -f $percent, $status)\n"
                "    Write-Log $status\n"
                "}\n"
                "Set-Content -Path $log -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' Update-Skript gestartet')\n"
                "Write-Host '104 Launcher wird aktualisiert...'\n"
                "Write-Host ''\n"
                "Show-Step 10 'Warte darauf, dass sich der Launcher beendet...'\n"
                "while (Get-Process -Id $pidToWait -ErrorAction SilentlyContinue) {\n"
                "    Start-Sleep -Seconds 1\n"
                "}\n"
                "Show-Step 35 'Launcher beendet. Bereite Dateiaustausch vor...'\n"
                "$copied = $false\n"
                "for ($attempt = 1; $attempt -le 10; $attempt++) {\n"
                "    try {\n"
                "        Show-Step 60 ('Kopiere Update-Datei... Versuch ' + $attempt + ' von 10')\n"
                "        if (Test-Path $backup) { Remove-Item -Path $backup -Force -ErrorAction SilentlyContinue }\n"
                "        if (Test-Path $target) { Move-Item -Path $target -Destination $backup -Force }\n"
                "        Move-Item -Path $source -Destination $target -Force\n"
                "        $copied = $true\n"
                "        Show-Step 85 'Dateien erfolgreich ersetzt.'\n"
                "        break\n"
                "    } catch {\n"
                "        Write-Host ('      Fehler: {0}' -f $_.Exception.Message)\n"
                "        Write-Log (\"Copy fehlgeschlagen, Versuch {0}: {1}\" -f $attempt, $_.Exception.Message)\n"
                "        if ((-not (Test-Path $target)) -and (Test-Path $backup)) {\n"
                "            Move-Item -Path $backup -Destination $target -Force -ErrorAction SilentlyContinue\n"
                "        }\n"
                "        Start-Sleep -Seconds 1\n"
                "    }\n"
                "}\n"
                "if (-not $copied) {\n"
                "    Show-Step 100 'Update fehlgeschlagen.'\n"
                "    Write-Host ''\n"
                "    Write-Host 'Das Update konnte nicht installiert werden. Details stehen in:'\n"
                "    Write-Host $log\n"
                "    Start-Sleep -Seconds 8\n"
                "    exit 1\n"
                "}\n"
                "Show-Step 92 'Pruefe neue Launcher-Datei...'\n"
                "$ready = $false\n"
                "for ($attempt = 1; $attempt -le 10; $attempt++) {\n"
                "    try {\n"
                "        $stream = [System.IO.File]::Open($target, 'Open', 'Read', 'ReadWrite')\n"
                "        $stream.Close()\n"
                "        $ready = $true\n"
                "        break\n"
                "    } catch {\n"
                "        Write-Log (\"Launcher-Datei noch nicht bereit, Versuch {0}: {1}\" -f $attempt, $_.Exception.Message)\n"
                "        Start-Sleep -Seconds 2\n"
                "    }\n"
                "}\n"
                "if (-not $ready) {\n"
                "    Show-Step 100 'Neue Launcher-Datei konnte nicht vorbereitet werden.'\n"
                "    Write-Host ''\n"
                "    Write-Host 'Die neue Launcher-Datei ist noch blockiert oder unvollstaendig.'\n"
                "    Write-Host 'Details stehen in:'\n"
                "    Write-Host $log\n"
                "    Start-Sleep -Seconds 8\n"
                "    exit 1\n"
                "}\n"
                "Show-Step 95 'Starte den aktualisierten Launcher neu...'\n"
                "$started = $false\n"
                "for ($attempt = 1; $attempt -le 5; $attempt++) {\n"
                "    try {\n"
                "        Start-Process -FilePath $target -WorkingDirectory (Split-Path -Path $target -Parent)\n"
                "        $started = $true\n"
                "        break\n"
                "    } catch {\n"
                "        Write-Host ('      Start fehlgeschlagen: {0}' -f $_.Exception.Message)\n"
                "        Write-Log (\"Launcher-Start fehlgeschlagen, Versuch {0}: {1}\" -f $attempt, $_.Exception.Message)\n"
                "        Start-Sleep -Seconds 2\n"
                "    }\n"
                "}\n"
                "if (-not $started) {\n"
                "    Show-Step 100 'Launcher konnte nicht neu gestartet werden.'\n"
                "    Write-Host ''\n"
                "    Write-Host 'Der Launcher wurde ersetzt, konnte aber nicht automatisch neu starten.'\n"
                "    Write-Host 'Bitte starte ihn manuell. Details stehen in:'\n"
                "    Write-Host $log\n"
                "    Start-Sleep -Seconds 10\n"
                "    exit 1\n"
                "}\n"
                "Show-Step 100 'Fertig. Der Launcher wird jetzt neu gestartet.'\n"
                "Write-Host ''\n"
                "Write-Host 'Update abgeschlossen.'\n"
                "if (Test-Path $backup) { Remove-Item -Path $backup -Force -ErrorAction SilentlyContinue }\n"
                "if (Test-Path $source) { Remove-Item -Path $source -Force -ErrorAction SilentlyContinue }\n"
                "Remove-Item -Path $PSCommandPath -Force -ErrorAction SilentlyContinue\n"
                "Start-Sleep -Seconds 3\n"
            )

            with open(updater_script, "w", encoding="utf-8") as fh:
                fh.write(script_content)

            subprocess.Popen(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    updater_script,
                ],
                creationflags=(
                    subprocess.CREATE_NEW_PROCESS_GROUP
                    | subprocess.CREATE_NEW_CONSOLE
                ),
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

    def _set_launch_buttons_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.launch_btn.configure(state=state)
        self.singleplayer_btn.configure(state=state)

    def _start_server_launch(self) -> None:
        self._start_launch_mode(join_server=True, use_teamspeak=True)

    def _start_singleplayer_launch(self) -> None:
        self._start_launch_mode(join_server=False, use_teamspeak=False)

    def _start_launch_mode(self, join_server: bool, use_teamspeak: bool) -> None:
        self.selected_arma_exe = self.ent_arma.get().strip()
        self.selected_ts_exe = self.ent_ts.get().strip()
        self.selected_ts_plugins_dir = self.ent_ts_plugins.get().strip()
        self.cfg["arma3_exe"] = self.selected_arma_exe
        self.cfg["teamspeak_exe"] = self.selected_ts_exe
        self.cfg["teamspeak_plugins_dir"] = self.selected_ts_plugins_dir
        save_config(self.cfg)
        self._set_launch_buttons_enabled(False)
        self._set_status("Starte...", "#ff9800")
        threading.Thread(
            target=self._launch_worker,
            args=(join_server, use_teamspeak),
            daemon=True,
        ).start()

    def _launch_worker(self, join_server: bool, use_teamspeak: bool) -> None:
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

                self._log("[INFO] Nach dem Abonnieren bitte erneut starten.")
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
            ]

            if join_server:
                args.extend([
                    f"-connect={SERVER_IP}",
                    f"-port={SERVER_PORT}",
                    f"-password={SERVER_PW}",
                ])

            self._log(f"\n[CMD] {arma3_exe}")
            self._log(f"      -mod=({len(mod_paths)} Mods)")
            if join_server:
                self._log(f"      -connect={SERVER_IP} -port={SERVER_PORT}")
            else:
                self._log("      [MODE] Singleplayer (kein TeamSpeak, kein Server-Connect)")
            # Jeden Mod-Pfad einzeln ausgeben damit man sieht was übergeben wird
            for i, p in enumerate(mod_paths, 1):
                self._log(f"      [{i:02d}] {p}")

            if use_teamspeak:
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
                self.after(0, lambda: self._set_launch_buttons_enabled(True))

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
        self.after(0, lambda: self._set_launch_buttons_enabled(True))

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