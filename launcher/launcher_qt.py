#!/usr/bin/env python3
"""
104 Launcher - PySide6 UI
"""

from __future__ import annotations

import csv
import ctypes
from ctypes import wintypes
import glob
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from typing import Optional

import requests
from PySide6.QtCore import QObject, Qt, Signal, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import backend


class LauncherWindow(QMainWindow):
    log_signal = Signal(str)
    status_signal = Signal(str, str)
    set_launch_buttons_enabled_signal = Signal(bool)
    invoke_main_signal = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.cfg = backend.load_config()
        self.ts_proc: Optional[subprocess.Popen] = None
        self.ts_url_pid: Optional[int] = None
        self.started_ts_pids: set[int] = set()
        self.selected_arma_exe = ""
        self.selected_ts_exe = ""
        self.selected_ts_plugins_dir = ""
        self._aspect_w = 1000
        self._aspect_h = 1337
        self._muted_ts_pids: set[int] = set()

        self.setWindowTitle("Strike Platoon | Arma 3 Launcher")
        self._set_window_icon()
        self._configure_window_size_from_background()
        self._center_window_on_screen()

        self.log_signal.connect(self._append_log)
        self.status_signal.connect(self._set_status_on_ui)
        self.set_launch_buttons_enabled_signal.connect(self._set_launch_buttons_enabled_on_ui)
        self.invoke_main_signal.connect(self._run_on_ui)

        self._build_ui()
        self._load_paths_into_ui()

        QTimer.singleShot(800, lambda: threading.Thread(target=self._check_launcher_update, daemon=True).start())

    def _set_window_icon(self) -> None:
        if os.path.isfile(backend.LOGO_ICO_PATH):
            self.setWindowIcon(QIcon(backend.LOGO_ICO_PATH))

    def _hidden_subprocess_kwargs(self) -> dict:
        if os.name != "nt":
            return {}

        kwargs: dict = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
        startup_cls = getattr(subprocess, "STARTUPINFO", None)
        startf_flag = getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
        if startup_cls is not None and startf_flag:
            startup = startup_cls()
            startup.dwFlags |= startf_flag
            startup.wShowWindow = 0
            kwargs["startupinfo"] = startup
        return kwargs

    def _configure_window_size_from_background(self) -> None:
        # Keep launcher sizing aligned to the intended background aspect (1000:1337).
        base_w = self._aspect_w
        base_h = self._aspect_h
        ratio = base_w / base_h
        screen_w = 1280
        screen_h = 720
        app = QApplication.instance()
        if app is not None and app.primaryScreen() is not None:
            geometry = app.primaryScreen().availableGeometry()
            screen_w = max(geometry.width(), 1280)
            screen_h = max(geometry.height(), 720)

        # Target around 80% of available screen height, while keeping horizontal margins.
        target_h = int(screen_h * 0.80)
        max_h_by_width = int((screen_w * 0.90) / ratio)
        target_h = min(target_h, max_h_by_width)
        target_h = max(target_h, int(base_h * 0.55))
        target_w = int(round(target_h * ratio))

        min_scale = 0.58
        min_w = max(680, int(base_w * min_scale))
        min_h = max(860, int(base_h * min_scale))

        self.resize(target_w, target_h)
        self.setMinimumSize(min_w, min_h)

    def _center_window_on_screen(self) -> None:
        app = QApplication.instance()
        if app is None or app.primaryScreen() is None:
            return

        geometry = app.primaryScreen().availableGeometry()
        x = geometry.x() + (geometry.width() - self.width()) // 2
        y = geometry.y() + (geometry.height() - self.height()) // 2
        self.move(x, y)

    def _build_ui(self) -> None:
        root = QWidget(self)
        root.setObjectName("root")
        self.setCentralWidget(root)
        self.bg_label = QLabel(root)
        self.bg_label.setObjectName("background")
        self.bg_label.setScaledContents(True)
        if os.path.isfile(backend.BACKGROUND_IMAGE_PATH):
            self.bg_label.setPixmap(QPixmap(backend.BACKGROUND_IMAGE_PATH))

        hero = QWidget(root)
        hero.setObjectName("hero")
        hero.setAttribute(Qt.WA_TranslucentBackground, True)
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(20, 14, 20, 14)
        hero_layout.setSpacing(10)

        self.logo_label = QLabel()
        self.logo_label.setAlignment(Qt.AlignCenter)
        if os.path.isfile(backend.LOGO_PNG_PATH):
            logo = QPixmap(backend.LOGO_PNG_PATH)
            self.logo_label.setPixmap(logo.scaled(260, 260, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        hero_layout.addWidget(self.logo_label)

        self.launch_btn = QPushButton("Server betreten")
        self.launch_btn.setObjectName("launchButton")
        self.launch_btn.setFixedSize(280, 54)
        self.launch_btn.clicked.connect(lambda: self._start_launch_mode(join_server=True, use_teamspeak=True))
        hero_layout.addWidget(self.launch_btn, alignment=Qt.AlignHCenter)

        self.singleplayer_btn = QPushButton("Singleplayer starten")
        self.singleplayer_btn.setObjectName("singleplayerButton")
        self.singleplayer_btn.setFixedSize(210, 40)
        self.singleplayer_btn.clicked.connect(lambda: self._start_launch_mode(join_server=False, use_teamspeak=False))
        hero_layout.addWidget(self.singleplayer_btn, alignment=Qt.AlignHCenter)

        self.status_lbl = QLabel("Bereit")
        self.status_lbl.setObjectName("statusLabel")
        self.status_lbl.setAlignment(Qt.AlignCenter)
        hero_layout.addWidget(self.status_lbl)

        self.hero = hero

        self.paths_frame = QFrame(root)
        self.paths_frame.setObjectName("pathsFrame")
        paths_layout = QGridLayout(self.paths_frame)
        paths_layout.setContentsMargins(8, 8, 8, 8)
        paths_layout.setHorizontalSpacing(8)
        paths_layout.setVerticalSpacing(8)

        paths_layout.addWidget(QLabel("Arma 3 EXE"), 0, 0)
        self.ent_arma = QLineEdit()
        self.ent_arma.editingFinished.connect(lambda: self._save_paths(log_message=False))
        paths_layout.addWidget(self.ent_arma, 0, 1)
        btn_arma = QPushButton("...")
        btn_arma.setObjectName("pathBrowseButton")
        btn_arma.setFixedWidth(40)
        btn_arma.setFixedHeight(28)
        btn_arma.clicked.connect(self._browse_arma)
        paths_layout.addWidget(btn_arma, 0, 2)

        paths_layout.addWidget(QLabel("TS3 EXE"), 1, 0)
        self.ent_ts = QLineEdit()
        self.ent_ts.editingFinished.connect(lambda: self._save_paths(log_message=False))
        paths_layout.addWidget(self.ent_ts, 1, 1)
        btn_ts = QPushButton("...")
        btn_ts.setObjectName("pathBrowseButton")
        btn_ts.setFixedWidth(40)
        btn_ts.setFixedHeight(28)
        btn_ts.clicked.connect(self._browse_ts)
        paths_layout.addWidget(btn_ts, 1, 2)

        paths_layout.addWidget(QLabel("TS3 Pluginpfad"), 2, 0)
        self.ent_ts_plugins = QLineEdit()
        self.ent_ts_plugins.editingFinished.connect(lambda: self._save_paths(log_message=False))
        paths_layout.addWidget(self.ent_ts_plugins, 2, 1)
        btn_plugins = QPushButton("...")
        btn_plugins.setObjectName("pathBrowseButton")
        btn_plugins.setFixedWidth(40)
        btn_plugins.setFixedHeight(28)
        btn_plugins.clicked.connect(self._browse_ts_plugins)
        paths_layout.addWidget(btn_plugins, 2, 2)

        self.btn_detect = QPushButton("Auto erkennen")
        self.btn_detect.setObjectName("pathActionButton")
        self.btn_detect.setFixedWidth(118)
        self.btn_detect.setFixedHeight(30)
        self.btn_detect.clicked.connect(lambda: self._auto_detect_paths(save=True))
        paths_layout.addWidget(self.btn_detect, 0, 3, 1, 1, Qt.AlignTop)

        paths_layout.setColumnStretch(1, 1)
        self.paths_frame.setVisible(False)

        self.log_box = QTextEdit(root)
        self.log_box.setObjectName("logBox")
        self.log_box.setReadOnly(True)
        self.log_box.setMinimumHeight(180)
        self.log_box.setVisible(False)

        self.bottom_frame = QFrame(root)
        self.bottom_frame.setObjectName("bottomFrame")
        bar = QHBoxLayout(self.bottom_frame)
        bar.setContentsMargins(8, 8, 8, 8)
        bar.setSpacing(8)

        self.open_arma_folder_btn = QPushButton("Arma 3 Ordner öffnen")
        self.open_arma_folder_btn.setMinimumHeight(42)
        self.open_arma_folder_btn.clicked.connect(self._open_arma_folder)
        bar.addWidget(self.open_arma_folder_btn)

        self.toggle_log_btn = QPushButton("Launcher Logs")
        self.toggle_log_btn.setMinimumHeight(42)
        self.toggle_log_btn.clicked.connect(self._toggle_log_visibility)
        bar.addWidget(self.toggle_log_btn)

        self.discord_btn = QPushButton("Discord")
        self.discord_btn.setMinimumHeight(42)
        self.discord_btn.clicked.connect(lambda: webbrowser.open(backend.DISCORD_URL))
        bar.addWidget(self.discord_btn)

        self.path_toggle_btn = QPushButton("Pfade anpassen")
        self.path_toggle_btn.setMinimumHeight(42)
        self.path_toggle_btn.clicked.connect(self._toggle_paths_visibility)
        bar.addWidget(self.path_toggle_btn)

        self._apply_styles()
        self._update_layout_geometry()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._update_layout_geometry()

    def nativeEvent(self, eventType, message):  # type: ignore[override]
        if os.name != "nt":
            return super().nativeEvent(eventType, message)

        WM_SIZING = 0x0214
        WMSZ_LEFT = 1
        WMSZ_RIGHT = 2
        WMSZ_TOP = 3
        WMSZ_TOPLEFT = 4
        WMSZ_TOPRIGHT = 5
        WMSZ_BOTTOM = 6
        WMSZ_BOTTOMLEFT = 7
        WMSZ_BOTTOMRIGHT = 8

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        msg = wintypes.MSG.from_address(int(message))
        if msg.message != WM_SIZING:
            return super().nativeEvent(eventType, message)

        rect_ptr = ctypes.cast(msg.lParam, ctypes.POINTER(RECT))
        rect = rect_ptr.contents
        edge = int(msg.wParam)

        width = max(1, rect.right - rect.left)
        height = max(1, rect.bottom - rect.top)
        ratio = self._aspect_w / self._aspect_h

        min_w = max(1, self.minimumWidth())
        min_h = max(1, self.minimumHeight())

        width_from_height = max(min_w, int(round(height * ratio)))
        height_from_width = max(min_h, int(round(width / ratio)))

        use_width_driver = abs(height_from_width - height) <= abs(width_from_height - width)
        target_w = width if use_width_driver else width_from_height
        target_h = height_from_width if use_width_driver else height

        target_w = max(min_w, target_w)
        target_h = max(min_h, target_h)

        is_left = edge in (WMSZ_LEFT, WMSZ_TOPLEFT, WMSZ_BOTTOMLEFT)
        is_top = edge in (WMSZ_TOP, WMSZ_TOPLEFT, WMSZ_TOPRIGHT)

        if is_left:
            rect.left = rect.right - target_w
        else:
            rect.right = rect.left + target_w

        if is_top:
            rect.top = rect.bottom - target_h
        else:
            rect.bottom = rect.top + target_h

        if edge in (WMSZ_LEFT, WMSZ_RIGHT):
            rect.bottom = rect.top + target_h
        elif edge in (WMSZ_TOP, WMSZ_BOTTOM):
            rect.right = rect.left + target_w

        return True, 0

    def _update_layout_geometry(self) -> None:
        width = self.width()
        height = self.height()

        self.bg_label.setGeometry(0, 0, width, height)

        side_margin = 24
        bottom_margin = 18
        bar_h = max(64, self.bottom_frame.sizeHint().height())
        bar_w = max(420, width - side_margin * 2)
        bar_x = (width - bar_w) // 2

        path_h = max(132, self.paths_frame.sizeHint().height())

        reserved_bottom = bar_h + bottom_margin + 10
        if self.paths_frame.isVisible():
            reserved_bottom += path_h + 10
        if self.log_box.isVisible():
            reserved_bottom += 220 + 10

        y_cursor = height - bottom_margin
        self.bottom_frame.setGeometry(bar_x, y_cursor - bar_h, bar_w, bar_h)
        y_cursor -= bar_h + 10

        hero_w = min(430, max(320, int(width * 0.42)))
        hero_h = min(430, max(320, int(height * 0.46)))
        hero_center_x = width // 2
        max_hero_bottom = height - reserved_bottom - 8
        hero_center_y = min(int(height * 0.44), max_hero_bottom - hero_h // 2)
        hero_center_y = max(hero_h // 2 + 24, hero_center_y)

        logo_size = min(240, max(180, int(height * 0.28)))
        if os.path.isfile(backend.LOGO_PNG_PATH):
            logo = QPixmap(backend.LOGO_PNG_PATH)
            self.logo_label.setPixmap(logo.scaled(logo_size, logo_size, Qt.KeepAspectRatio, Qt.SmoothTransformation))

        launch_w = min(300, max(240, int(width * 0.33)))
        self.launch_btn.setFixedSize(launch_w, 52)

        secondary_w = min(240, max(190, int(width * 0.26)))
        self.singleplayer_btn.setFixedSize(secondary_w, 38)

        self.hero.setGeometry(hero_center_x - hero_w // 2, hero_center_y - hero_h // 2, hero_w, hero_h)

        if self.paths_frame.isVisible():
            self.paths_frame.setGeometry(side_margin, y_cursor - path_h, width - side_margin * 2, path_h)
            y_cursor -= path_h + 10

        if self.log_box.isVisible():
            log_h = 220
            self.log_box.setGeometry(side_margin, max(18, y_cursor - log_h), width - side_margin * 2, log_h)

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow {
                background-color: #111721;
                color: #d7e3f0;
            }
            QWidget#root {
                background-color: transparent;
                color: #d7e3f0;
            }
            QWidget#hero {
                background-color: rgba(5, 16, 30, 96);
                border: 1px solid rgba(180, 208, 236, 72);
                border-radius: 18px;
            }
            QLabel#background {
                background-color: #102437;
            }
            QFrame#pathsFrame {
                background-color: rgba(10, 28, 45, 210);
                border: 1px solid rgba(111, 139, 170, 210);
                border-radius: 12px;
            }
            QFrame#bottomFrame {
                background-color: rgba(11, 31, 52, 190);
                border: 1px solid rgba(106, 133, 159, 190);
                border-radius: 12px;
            }
            QLineEdit {
                background-color: rgba(24, 50, 74, 230);
                border: 1px solid #6f8baa;
                padding: 6px;
                color: #d7e3f0;
                border-radius: 8px;
            }
            QTextEdit#logBox {
                background-color: rgba(16, 36, 55, 214);
                border: 1px solid #3d5c7d;
                color: #d7e3f0;
                border-radius: 10px;
            }
            QPushButton {
                min-height: 36px;
                border-radius: 10px;
                border: 1px solid #6a859f;
                background-color: rgba(39, 69, 107, 228);
                color: #e3edf7;
                font-size: 13px;
                padding: 4px 12px;
            }
            QPushButton:hover {
                background-color: rgba(53, 90, 135, 236);
            }
            QPushButton#launchButton {
                border-radius: 26px;
                border: 1px solid #d1e5c3;
                background-color: #2f8f5f;
                color: #eef7ee;
                font-size: 18px;
                font-weight: 700;
            }
            QPushButton#launchButton:hover {
                background-color: #236f4a;
            }
            QPushButton#singleplayerButton {
                border-radius: 19px;
                border: 1px solid #9cb2c8;
                background-color: #2a3f56;
                color: #e5eef8;
                font-size: 13px;
                font-weight: 700;
            }
            QPushButton#singleplayerButton:hover {
                background-color: #35526f;
            }
            QPushButton#pathBrowseButton {
                min-height: 24px;
                font-size: 12px;
                border-radius: 7px;
                padding: 1px 6px;
            }
            QPushButton#pathActionButton {
                min-height: 28px;
                font-size: 12px;
                border-radius: 8px;
                padding: 2px 8px;
            }
            QLabel#statusLabel {
                color: #b4cadf;
                font-size: 14px;
                font-weight: 700;
                background-color: rgba(6, 16, 30, 150);
                border: 1px solid rgba(170, 198, 228, 120);
                border-radius: 10px;
                padding: 3px 12px;
            }
            """
        )

    def _run_on_ui(self, fn: object) -> None:
        if callable(fn):
            fn()

    def _ask_yes_no_threadsafe(self, title: str, question: str) -> bool:
        if threading.current_thread() is threading.main_thread():
            return QMessageBox.question(self, title, question) == QMessageBox.Yes

        result = {"value": False}
        done = threading.Event()

        def _show() -> None:
            result["value"] = QMessageBox.question(self, title, question) == QMessageBox.Yes
            done.set()

        self.invoke_main_signal.emit(_show)
        done.wait()
        return bool(result["value"])

    def _append_log(self, msg: str) -> None:
        self.log_box.append(msg)
        self.log_box.verticalScrollBar().setValue(self.log_box.verticalScrollBar().maximum())

    def _log(self, msg: str) -> None:
        self.log_signal.emit(msg)

    def _set_status_on_ui(self, text: str, color: str) -> None:
        self.status_lbl.setText(text)
        self.status_lbl.setStyleSheet(f"color: {color};")

    def _set_status(self, text: str, color: str = "#546e7a") -> None:
        self.status_signal.emit(text, color)

    def _set_launch_buttons_enabled_on_ui(self, enabled: bool) -> None:
        self.launch_btn.setEnabled(enabled)
        self.singleplayer_btn.setEnabled(enabled)

    def _set_launch_buttons_enabled(self, enabled: bool) -> None:
        self.set_launch_buttons_enabled_signal.emit(enabled)

    def _toggle_log_visibility(self) -> None:
        visible = not self.log_box.isVisible()
        self.log_box.setVisible(visible)
        self.toggle_log_btn.setText("Logs ausblenden" if visible else "Launcher Logs")
        self._update_layout_geometry()

    def _toggle_paths_visibility(self) -> None:
        visible = not self.paths_frame.isVisible()
        self.paths_frame.setVisible(visible)
        self.path_toggle_btn.setText("Pfade ausblenden" if visible else "Pfade anpassen")
        self._update_layout_geometry()

    def _load_paths_into_ui(self) -> None:
        arma_cfg = self._normalize_path(self.cfg.get("arma3_exe", ""))
        ts_cfg = self._normalize_path(self.cfg.get("teamspeak_exe", ""))
        plugins_cfg = self._normalize_path(self.cfg.get("teamspeak_plugins_dir", ""), is_dir=True)

        if arma_cfg:
            self.ent_arma.setText(arma_cfg)
        if ts_cfg:
            self.ent_ts.setText(ts_cfg)
        if plugins_cfg:
            self.ent_ts_plugins.setText(plugins_cfg)

        if not self.ent_arma.text().strip() or not self.ent_ts.text().strip() or not self.ent_ts_plugins.text().strip():
            self._auto_detect_paths(save=False)

    def _save_paths(self, log_message: bool = True) -> None:
        self.cfg["arma3_exe"] = self._normalize_path(self.ent_arma.text())
        self.cfg["teamspeak_exe"] = self._normalize_path(self.ent_ts.text())
        self.cfg["teamspeak_plugins_dir"] = self._normalize_path(self.ent_ts_plugins.text(), is_dir=True)
        backend.save_config(self.cfg)
        if log_message:
            self._log("[OK] Pfade gespeichert.")

    def _normalize_path(self, value: str, is_dir: bool = False) -> str:
        path = (value or "").strip().strip('"').strip("'")
        if not path:
            return ""

        path = os.path.expandvars(os.path.expanduser(path))
        path = os.path.normpath(path)

        if is_dir:
            return path.rstrip("\\/")
        return path

    def _browse_arma(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "Arma 3 EXE auswählen", "", "Executable (*.exe)")
        if file_path:
            self.ent_arma.setText(file_path)
            self._save_paths(log_message=False)

    def _browse_ts(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(self, "TeamSpeak 3 EXE auswählen", "", "Executable (*.exe)")
        if file_path:
            self.ent_ts.setText(file_path)
            detected_plugins = self._detect_ts_plugins_dir(file_path)
            if detected_plugins:
                self.ent_ts_plugins.setText(detected_plugins)
            self._save_paths(log_message=False)

    def _browse_ts_plugins(self) -> None:
        folder_path = QFileDialog.getExistingDirectory(self, "TeamSpeak Pluginordner auswählen")
        if folder_path:
            self.ent_ts_plugins.setText(folder_path)
            self._save_paths(log_message=False)

    def _detect_ts_plugins_dir(self, ts_exe_path: str) -> str:
        ts_exe_path = self._normalize_path(ts_exe_path)
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

        for folder in candidates:
            if os.path.isdir(folder):
                return folder
        return ""

    def _resolve_teamspeak_exe(self) -> str:
        exe_names = ("ts3client_win64.exe", "ts3client_win32.exe")

        def _existing_file(path: str) -> str:
            normalized = self._normalize_path(path)
            if normalized and os.path.isfile(normalized):
                return normalized
            return ""

        manual = self._normalize_path(self.selected_ts_exe or self.ent_ts.text())
        if manual:
            direct = _existing_file(manual)
            if direct:
                return direct

            if os.path.isdir(manual):
                for exe_name in exe_names:
                    candidate = _existing_file(os.path.join(manual, exe_name))
                    if candidate:
                        return candidate
            else:
                parent = os.path.dirname(manual)
                if os.path.isdir(parent):
                    for exe_name in exe_names:
                        candidate = _existing_file(os.path.join(parent, exe_name))
                        if candidate:
                            return candidate

        detected = _existing_file(backend.find_teamspeak_exe() or "")
        if detected:
            return detected

        fallback_dirs = [
            os.path.join(os.environ.get("ProgramFiles", ""), "TeamSpeak 3 Client"),
            os.path.join(os.environ.get("ProgramFiles(x86)", ""), "TeamSpeak 3 Client"),
        ]
        for folder in fallback_dirs:
            if not os.path.isdir(folder):
                continue
            for exe_name in exe_names:
                candidate = _existing_file(os.path.join(folder, exe_name))
                if candidate:
                    return candidate

        return ""

    def _teamspeak_launch_candidates(self) -> list[str]:
        candidates: list[str] = []
        manual = self._normalize_path(self.selected_ts_exe or self.ent_ts.text())
        if manual:
            candidates.append(manual)

        resolved = self._resolve_teamspeak_exe()
        if resolved and resolved not in candidates:
            candidates.append(resolved)

        return candidates

    def _auto_detect_paths(self, save: bool = True) -> None:
        steam = backend.find_steam_path()
        arma_path = ""
        if steam:
            arma_path, _ = backend.find_arma3(steam)
            arma_path = self._normalize_path(arma_path or "")

        ts_path = self._normalize_path(backend.find_teamspeak_exe() or "")
        plugins_path = self._detect_ts_plugins_dir(ts_path)

        if arma_path:
            self.ent_arma.setText(arma_path)
            self._log(f"[OK] Arma 3 erkannt: {arma_path}")
        else:
            self._log("[WARN] Arma 3 EXE konnte nicht automatisch erkannt werden.")

        if ts_path:
            self.ent_ts.setText(ts_path)
            self._log(f"[OK] TeamSpeak erkannt: {ts_path}")
        else:
            self._log("[WARN] TeamSpeak EXE konnte nicht automatisch erkannt werden.")

        if plugins_path:
            self.ent_ts_plugins.setText(plugins_path)
            self._log(f"[OK] TeamSpeak Pluginpfad erkannt: {plugins_path}")
        else:
            self._log("[WARN] TeamSpeak Pluginpfad konnte nicht automatisch erkannt werden.")

        if save:
            self._save_paths(log_message=False)

    def _open_arma_folder(self) -> None:
        arma_exe = self._normalize_path(self.ent_arma.text())
        if not arma_exe:
            self._log("[WARN] Kein Arma 3 Pfad gesetzt. Bitte erst unter 'Pfade anpassen' eintragen.")
            return

        arma_dir = os.path.dirname(arma_exe)
        if os.path.isdir(arma_dir):
            os.startfile(arma_dir)
            self._log(f"[INFO] Arma 3 Ordner geoeffnet: {arma_dir}")
        else:
            self._log(f"[WARN] Arma 3 Ordner nicht gefunden: {arma_dir}")

    def _find_workshop_by_arma_exe(self, arma3_exe: str) -> Optional[str]:
        game_dir = os.path.normpath(os.path.dirname(arma3_exe))

        steam = backend.find_steam_path()
        if steam:
            for steamapps in backend.find_all_steam_libraries(steam):
                candidate_game_dir = os.path.normpath(os.path.join(steamapps, "common", "Arma 3"))
                if os.path.normcase(candidate_game_dir) == os.path.normcase(game_dir):
                    return os.path.join(steamapps, "workshop", "content", backend.ARMA3_APP_ID)

        marker = f"{os.sep}steamapps{os.sep}common{os.sep}Arma 3"
        lower_game_dir = game_dir.lower()
        marker_index = lower_game_dir.rfind(marker.lower())
        if marker_index != -1:
            steamapps = game_dir[:marker_index] + f"{os.sep}steamapps"
            return os.path.join(steamapps, "workshop", "content", backend.ARMA3_APP_ID)

        return None

    def _find_mod_folder(self, mod_id: str, preferred_workshop_path: Optional[str]) -> Optional[str]:
        candidates: list[str] = []
        if preferred_workshop_path:
            candidates.append(os.path.join(preferred_workshop_path, mod_id))

        steam = backend.find_steam_path()
        if steam:
            for steamapps in backend.find_all_steam_libraries(steam):
                workshop = os.path.join(steamapps, "workshop", "content", backend.ARMA3_APP_ID, mod_id)
                if workshop not in candidates:
                    candidates.append(workshop)

        for candidate in candidates:
            if os.path.isdir(candidate):
                return candidate
        return None

    def _open_missing_mods_in_steam(self, missing_mods: list[dict]) -> None:
        for mod in missing_mods:
            mod_id = mod.get("id", "")
            mod_name = mod.get("name", "Unbekannt")
            steam_url = f"steam://url/CommunityFilePage/{mod_id}"
            web_url = f"https://steamcommunity.com/sharedfiles/filedetails/?id={mod_id}"
            opened = webbrowser.open(steam_url)
            if not opened:
                webbrowser.open(web_url)
            self._log(f"[INFO] Workshop geoeffnet: {mod_name} ({mod_id})")

    def _is_tfar_plugin_installed(self) -> bool:
        plugins_dir = self._normalize_path(self.selected_ts_plugins_dir or self.ent_ts_plugins.text(), is_dir=True)
        if not plugins_dir:
            plugins_dir = self._detect_ts_plugins_dir(self.selected_ts_exe or self.ent_ts.text())

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
        target_file = os.path.join(tempfile.gettempdir(), "task_force_radio.ts3_plugin")
        self._log(f"[INFO] Lade TFAR-Plugin herunter: {backend.TFAR_PLUGIN_DOWNLOAD_URL}")
        try:
            response = requests.get(backend.TFAR_PLUGIN_DOWNLOAD_URL, timeout=60)
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

    def _list_teamspeak_pids(self) -> set[int]:
        pids: set[int] = set()
        exe_names = ("ts3client_win64.exe", "ts3client_win32.exe")

        for exe_name in exe_names:
            try:
                output = subprocess.check_output(
                    ["tasklist", "/FI", f"IMAGENAME eq {exe_name}", "/FO", "CSV", "/NH"],
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    **self._hidden_subprocess_kwargs(),
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

    def _close_running_teamspeak_instances(self) -> bool:
        existing_pids = sorted(self._list_teamspeak_pids())
        if not existing_pids:
            return True

        self._log(f"[INFO] TeamSpeak laeuft bereits. Beende {len(existing_pids)} Instanz(en) fuer sauberen Neustart...")
        failed: list[int] = []
        for pid in existing_pids:
            if self._kill_pid_tree(pid):
                self._log(f"[OK] TeamSpeak-Instanz beendet (PID {pid}).")
            else:
                failed.append(pid)
                self._log(f"[WARN] TeamSpeak-Instanz konnte nicht beendet werden (PID {pid}).")

        time.sleep(1.0)
        remaining = sorted(self._list_teamspeak_pids())
        if remaining:
            self._log(
                "[FEHLER] TeamSpeak konnte nicht vollstaendig beendet werden. "
                f"Restliche PID(s): {', '.join(str(pid) for pid in remaining)}"
            )
            return False

        if failed:
            return False

        self.ts_proc = None
        self.ts_url_pid = None
        self.started_ts_pids.clear()
        self._muted_ts_pids.clear()
        return True

    def _connect_teamspeak_server(self, ts_exe: str, ts_url: str) -> bool:
        if webbrowser.open(ts_url):
            self._log("[OK] TeamSpeak-Serververbindung ueber ts3server:// geoeffnet.")
            return True

        self._log("[WARN] TeamSpeak-Verbindung per Browser-Handler fehlgeschlagen. Versuche Fallbacks...")

        if os.name == "nt":
            try:
                os.startfile(ts_url)  # type: ignore[attr-defined]
                self._log("[OK] TeamSpeak-Serververbindung ueber os.startfile(ts3server://) geoeffnet.")
                return True
            except Exception:
                pass

        for extra_args in ([ts_url], ["-nosingleinstance", ts_url]):
            try:
                subprocess.Popen([ts_exe, *extra_args], cwd=os.path.dirname(ts_exe))
                self._log("[OK] TeamSpeak-Serververbindung ueber EXE-Fallback gestartet.")
                return True
            except Exception:
                continue

        self._log("[WARN] TeamSpeak-Serververbindung konnte auch mit Fallback nicht geoeffnet werden.")
        return False

    def _start_teamspeak_managed(self) -> bool:
        ts_url = f"ts3server://{backend.TS3_IP}?port={backend.TS3_PORT}"

        manual_ts_path = self._normalize_path(self.selected_ts_exe or self.ent_ts.text())
        ts_exe = manual_ts_path if os.path.isfile(manual_ts_path) else None
        if not ts_exe:
            ts_exe = self._resolve_teamspeak_exe()
        if not ts_exe:
            if manual_ts_path:
                self._log(f"[WARN] TeamSpeak-Pfad ungueltig oder nicht gefunden: {manual_ts_path}")
            self._log("[FEHLER] TeamSpeak 3 ist nicht installiert oder nicht gefunden.")
            install_now = self._ask_yes_no_threadsafe(
                "TeamSpeak 3 fehlt",
                "TeamSpeak 3 wurde nicht gefunden. Moechtest du jetzt installieren?",
            )
            if install_now:
                webbrowser.open(backend.TS3_DOWNLOAD_URL)
                self._log(f"[INFO] TeamSpeak Downloadseite geoeffnet: {backend.TS3_DOWNLOAD_URL}")
            self.ts_proc = None
            return False

        self.ent_ts.setText(ts_exe)
        self.selected_ts_exe = ts_exe

        if not self._close_running_teamspeak_instances():
            self._log("[FEHLER] TeamSpeak-Neustart nicht moeglich. Bitte TeamSpeak manuell schliessen und erneut versuchen.")
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

        self.ts_url_pid = None
        self.started_ts_pids.clear()
        self._muted_ts_pids.clear()
        before_pids = self._list_teamspeak_pids()
        args_no_sound = [ts_exe, "-nosingleinstance", "-nosound"]
        args_fallback = [ts_exe, "-nosingleinstance"]

        try:
            self._log("[INFO] Starte TeamSpeak mit deaktivierten Sounds...")
            self.ts_proc = subprocess.Popen(args_no_sound, cwd=os.path.dirname(ts_exe))
            time.sleep(1.2)
            if self.ts_proc.poll() is not None:
                self._log("[WARN] TeamSpeak hat '-nosound' nicht akzeptiert. Starte ohne Sound-Flag neu.")
                self.ts_proc = subprocess.Popen(args_fallback, cwd=os.path.dirname(ts_exe))

            self._connect_teamspeak_server(ts_exe, ts_url)
        except OSError as exc:
            if getattr(exc, "winerror", None) == 740:
                self._log("[WARN] TeamSpeak verlangt erhoehte Rechte (WinError 740).")
                self._log("[HINWEIS] Starte TeamSpeak jetzt explizit erhoeht (runas).")

                params_no_sound = "-nosingleinstance -nosound"
                params_fallback = "-nosingleinstance"

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
                    self._connect_teamspeak_server(ts_exe, ts_url)
                    time.sleep(1.5)
                    after = self._list_teamspeak_pids()
                    new_pids = sorted(after - before)
                    if new_pids:
                        self.ts_url_pid = new_pids[-1]
                        self.started_ts_pids.update(new_pids)
                        self._log(f"[INFO] TeamSpeak PID fuer Auto-Beenden gemerkt: {self.ts_url_pid}")
                    else:
                        self._log("[WARN] Keine neue TeamSpeak-PID erkannt. Laufende TS-Instanz wird nicht automatisch beendet.")
                    self._mute_teamspeak_audio_sessions(self.started_ts_pids)
                    self.ts_proc = None
                    return True

                self._log("[WARN] Erhoehter TeamSpeak-Start fehlgeschlagen. Fallback auf ts3server://-Start.")
                before = self._list_teamspeak_pids()
                if self._connect_teamspeak_server(ts_exe, ts_url):
                    self._log("[OK] TeamSpeak per Protokoll-URL gestartet.")
                    time.sleep(1.5)
                    after = self._list_teamspeak_pids()
                    new_pids = sorted(after - before)
                    if new_pids:
                        self.ts_url_pid = new_pids[-1]
                        self.started_ts_pids.update(new_pids)
                        self._log(f"[INFO] TeamSpeak PID fuer Auto-Beenden gemerkt: {self.ts_url_pid}")
                    else:
                        self._log("[WARN] Keine neue TeamSpeak-PID erkannt. Laufende TS-Instanz wird nicht automatisch beendet.")
                    self._mute_teamspeak_audio_sessions(self.started_ts_pids)
                    self.ts_proc = None
                    return True
                self._log("[FEHLER] TeamSpeak konnte auch per Protokoll-URL nicht gestartet werden.")
            else:
                self._log(f"[FEHLER] TeamSpeak konnte nicht gestartet werden: {exc}")
            self.ts_proc = None
            return False

        self._log(f"[OK] TeamSpeak gestartet (PID: {self.ts_proc.pid})")
        try:
            after_pids = self._list_teamspeak_pids()
            self.started_ts_pids = set(after_pids - before_pids)
            if self.started_ts_pids:
                self._log(f"[INFO] TeamSpeak-PIDs fuer Auto-Beenden: {', '.join(str(pid) for pid in sorted(self.started_ts_pids))}")
        except Exception:
            self.started_ts_pids = set()

        self._mute_teamspeak_audio_sessions(self.started_ts_pids)
        return True

    def _mute_teamspeak_audio_sessions(self, ts_pids: set[int]) -> None:
        target_names = {"ts3client_win64.exe", "ts3client_win32.exe"}

        try:
            from pycaw.pycaw import AudioUtilities  # type: ignore[import-not-found]
        except Exception:
            self._log("[INFO] pycaw nicht verfuegbar: TeamSpeak-Sessions konnten nicht automatisch stummgeschaltet werden.")
            return

        for attempt in range(1, 7):
            muted_any = False
            try:
                sessions = AudioUtilities.GetAllSessions()
                for session in sessions:
                    process = getattr(session, "Process", None)
                    if process is None:
                        continue

                    process_pid = int(getattr(process, "pid", 0) or 0)
                    process_name = str(getattr(process, "name", lambda: "")() or "").lower()

                    is_target_pid = bool(ts_pids) and process_pid in ts_pids
                    is_target_name = process_name in target_names
                    if not (is_target_pid or is_target_name):
                        continue

                    volume = getattr(session, "SimpleAudioVolume", None)
                    if volume is None:
                        continue

                    volume.SetMute(1, None)
                    if process_pid:
                        self._muted_ts_pids.add(process_pid)
                    muted_any = True

                if muted_any:
                    self._log("[OK] TeamSpeak-Audio (Event-Sounds) wurde fuer gestartete Instanz stummgeschaltet.")
                    return
            except Exception as exc:
                self._log(f"[WARN] TeamSpeak-Audio konnte nicht stummgeschaltet werden: {exc}")
                return

            if attempt < 6:
                time.sleep(0.6)

        self._log("[WARN] TeamSpeak-Audio-Session zum Stummschalten nicht gefunden.")

    def _kill_pid_tree(self, pid: int) -> bool:
        try:
            result = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T"],
                capture_output=True,
                text=True,
                **self._hidden_subprocess_kwargs(),
            )
            if result.returncode == 0:
                return True

            result_force = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                **self._hidden_subprocess_kwargs(),
            )
            if result_force.returncode == 0:
                return True

            # If TS was started elevated (runas), non-elevated taskkill may fail.
            rc = ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                "cmd.exe",
                f'/c taskkill /PID {pid} /T /F',
                None,
                0,
            )
            if rc <= 32:
                return False

            time.sleep(1.2)
            check = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                **self._hidden_subprocess_kwargs(),
            )
            output = (check.stdout or "").strip().lower()
            return ("no tasks are running" in output) or ("keine aufgaben" in output) or not output
        except Exception:
            return False

    def _parse_version_parts(self, version_text: str) -> tuple[int, ...]:
        parts = re.findall(r"\d+", version_text)
        if not parts:
            return (0,)
        return tuple(int(part) for part in parts)

    def _get_latest_release_info(self) -> tuple[str, Optional[str], str]:
        last_error: Optional[Exception] = None
        for attempt in range(3):
            try:
                response = requests.get(
                    backend.GITHUB_API_LATEST_RELEASE_URL,
                    headers=backend.GITHUB_API_HEADERS,
                    timeout=15,
                )
                response.raise_for_status()
                break
            except requests.RequestException as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise

        if last_error is not None and "response" not in locals():
            raise last_error

        release = response.json()
        remote_version = str(release.get("tag_name") or "").strip()
        if not remote_version:
            raise ValueError("GitHub Release enthaelt kein tag_name")

        release_page_url = str(release.get("html_url") or backend.GITHUB_RELEASES_URL)
        assets = release.get("assets") or []
        asset_url: Optional[str] = None

        for asset_name in backend.LAUNCHER_ASSET_NAMES:
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
        try:
            self._log(f"[INFO] Pruefe Launcher-Version (lokal: {backend.LAUNCHER_VERSION})...")
            remote_version, download_url, release_page_url = self._get_latest_release_info()

            local_parts = self._parse_version_parts(backend.LAUNCHER_VERSION)
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
                        self.invoke_main_signal.emit(self._exit_for_update)
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
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status in (502, 503, 504):
                self._log("[INFO] GitHub ist gerade nicht erreichbar (Serverfehler). Update-Check wird spaeter erneut versucht.")
            elif status == 403:
                self._log("[INFO] GitHub API-Limit erreicht. Update-Check spaeter erneut versuchen.")
            else:
                self._log(f"[WARN] Update-Check fehlgeschlagen: {exc}")
        except (requests.Timeout, requests.ConnectionError):
            self._log("[INFO] Netzwerkproblem beim Update-Check. Wird beim naechsten Start erneut versucht.")
        except Exception as exc:
            self._log(f"[WARN] Update-Check fehlgeschlagen: {exc}")

    def _exit_for_update(self) -> None:
        try:
            self.close()
        finally:
            os._exit(0)

    def _download_and_apply_update(self, remote_version: str, download_url: str) -> bool:
        if not getattr(sys, "frozen", False):
            self._log("[INFO] Auto-Update nur im EXE-Modus verfuegbar.")
            return False

        current_exe = os.path.abspath(sys.executable)
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

    def _start_launch_mode(self, join_server: bool, use_teamspeak: bool) -> None:
        self.selected_arma_exe = self._normalize_path(self.ent_arma.text())
        self.selected_ts_exe = self._normalize_path(self.ent_ts.text())
        self.selected_ts_plugins_dir = self._normalize_path(self.ent_ts_plugins.text(), is_dir=True)
        self.ent_arma.setText(self.selected_arma_exe)
        self.ent_ts.setText(self.selected_ts_exe)
        self.ent_ts_plugins.setText(self.selected_ts_plugins_dir)
        self.cfg["arma3_exe"] = self.selected_arma_exe
        self.cfg["teamspeak_exe"] = self.selected_ts_exe
        self.cfg["teamspeak_plugins_dir"] = self.selected_ts_plugins_dir
        backend.save_config(self.cfg)

        self._set_launch_buttons_enabled(False)
        self._set_status("Starte...", "#ff9800")
        threading.Thread(target=self._launch_worker, args=(join_server, use_teamspeak), daemon=True).start()

    def _launch_worker(self, join_server: bool, use_teamspeak: bool) -> None:
        arma_started = False
        try:
            self._log("[INFO] Pruefe Arma 3 Pfad...")
            if self.selected_arma_exe and os.path.isfile(self.selected_arma_exe):
                arma3_exe = self.selected_arma_exe
                workshop_path = self._find_workshop_by_arma_exe(arma3_exe)
                self._log("[OK] Arma 3 aus manuellem Pfad.")
            else:
                steam = backend.find_steam_path()
                if not steam:
                    self._log("[FEHLER] Steam nicht gefunden und kein gueltiger Arma-Pfad gesetzt!")
                    self._set_status("Fehler", "#f44336")
                    return

                arma3_exe, workshop_path = backend.find_arma3(steam)
                if not arma3_exe:
                    self._log("[FEHLER] Arma 3 nicht gefunden!")
                    self._set_status("Fehler", "#f44336")
                    return
                self.ent_arma.setText(arma3_exe)
                self.cfg["arma3_exe"] = arma3_exe
                backend.save_config(self.cfg)
                self._log("[OK] Arma 3 automatisch erkannt und gespeichert.")

            self._log(f"[OK] Arma 3: {arma3_exe}")

            if not workshop_path or not os.path.isdir(workshop_path):
                self._log("[FEHLER] Workshop-Ordner konnte fuer diese Arma-Installation nicht gefunden werden.")
                self._set_status("Workshop fehlt", "#f44336")
                return

            self._log("[INFO] Lade Modlist...")
            self._set_status("Lade Modlist...", "#ff9800")
            try:
                resp = requests.get(backend.PRESET_URL, timeout=20)
                resp.raise_for_status()
                self._log(f"[OK] Modlist geladen ({len(resp.text):,} Bytes)")
            except requests.RequestException as exc:
                self._log(f"[FEHLER] Download fehlgeschlagen: {exc}")
                self._set_status("Fehler", "#f44336")
                return

            mods = backend.parse_preset(resp.text)
            if not mods:
                self._log("[FEHLER] Keine Mods in der Modlist gefunden!")
                self._set_status("Fehler", "#f44336")
                return
            self._log(f"[OK] {len(mods)} Mod(s) in der Liste")

            self._set_status("Pruefe Mods...", "#ff9800")
            mod_paths: list[str] = []
            missing: list[dict] = []

            for mod in mods:
                folder = self._find_mod_folder(mod["id"], workshop_path)
                if folder and os.path.isdir(folder):
                    has_addons = os.path.isdir(os.path.join(folder, "addons"))
                    if not has_addons:
                        self._log(f"  WARN {mod['name']} — kein 'addons' Unterordner! (unvollständig heruntergeladen?)")
                    mod_paths.append(folder)
                    status = "OK" if has_addons else "WARN"
                    self._log(f"  {status} {mod['name']}")
                else:
                    missing.append({"name": mod["name"], "id": mod["id"]})
                    self._log(f"  FEHLT: {mod['name']} ({mod['id']})")

            if missing:
                self._log(f"\n[FEHLER] {len(missing)} Mod(s) fehlen! Start abgebrochen.")
                self._log("[HINWEIS] Fehlende Mods zuerst im Arma 3 Launcher abonnieren/synchronisieren.")
                self._set_status("Fehlende Mods", "#f44336")
                for mod in missing:
                    ask = self._ask_yes_no_threadsafe("Mod abonnieren", f"Moechtest du {mod['name']} abonnieren?")
                    if ask:
                        self._open_missing_mods_in_steam([mod])
                        self._log(f"[INFO] Bitte Mod in Steam abonnieren: {mod['name']} ({mod['id']})")
                self._log("[INFO] Nach dem Abonnieren bitte erneut starten.")
                return

            invalid_addons = [mod_path for mod_path in mod_paths if not os.path.isdir(os.path.join(mod_path, "addons"))]
            if invalid_addons:
                self._log(f"\n[FEHLER] {len(invalid_addons)} Mod(s) ohne addons-Ordner gefunden! Start abgebrochen.")
                self._set_status("Defekte Mods", "#f44336")
                return

            if not mod_paths:
                self._log("[FEHLER] Keine Mods installiert. Zuerst Mods abonnieren!")
                self._set_status("Fehler", "#f44336")
                return

            args = [arma3_exe, f"-mod={';'.join(mod_paths)}"]
            if join_server:
                args.extend(
                    [
                        f"-connect={backend.SERVER_IP}",
                        f"-port={backend.SERVER_PORT}",
                        f"-password={backend.SERVER_PW}",
                    ]
                )

            if use_teamspeak:
                self._log("\n[INFO] Starte TeamSpeak 3...")
                ts_started = self._start_teamspeak_managed()
                if not ts_started:
                    self._set_status("TeamSpeak fehlt", "#f44336")
                    self._log("[INFO] Start abgebrochen bis TeamSpeak installiert ist.")
                    return

            self._log("[INFO] Starte Arma 3...")
            proc = subprocess.Popen(args, cwd=os.path.dirname(arma3_exe))
            arma_started = True
            self._log("[OK] Arma 3 gestartet! PID: " + str(proc.pid))
            self._set_status("Arma 3 laeuft...", "#4caf50")
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
                self._set_launch_buttons_enabled(True)

    def _watch_process(self, proc: subprocess.Popen) -> None:
        exit_code = proc.wait()
        self._log(f"\n[INFO] Arma 3 beendet. Exit-Code: {exit_code}")

        # Prefer explicit PID cleanup first, because ts3 can spawn a child and let launcher-tracked proc exit.
        if self.started_ts_pids:
            self._log("[INFO] Beende gestartete TeamSpeak-Prozesse...")
            for pid in sorted(self.started_ts_pids):
                closed = self._kill_pid_tree(pid)
                if closed:
                    self._log(f"[OK] TeamSpeak 3 Prozess beendet (PID {pid}).")
                else:
                    self._log(f"[WARN] TeamSpeak 3 Prozess konnte nicht beendet werden (PID {pid}).")
            self.started_ts_pids.clear()

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
            closed = self._kill_pid_tree(self.ts_url_pid)
            if closed:
                self._log("[OK] TeamSpeak 3 beendet.")
            else:
                self._log("[WARN] TeamSpeak 3 konnte nicht automatisch beendet werden (ggf. UAC abgelehnt).")
            self.ts_url_pid = None

        # Final safety net for leftover TS processes not captured by pid tracking.
        try:
            for pid in sorted(self._list_teamspeak_pids()):
                self._kill_pid_tree(pid)
        except Exception:
            pass

        if exit_code != 0:
            self._set_status(f"Arma 3 Crash (Code {exit_code})", "#f44336")
        else:
            self._set_status("Arma 3 beendet", "#546e7a")

        self._read_rpt_log()
        self._set_launch_buttons_enabled(True)

    def _read_rpt_log(self) -> None:
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


def main() -> None:
    app = QApplication([])

    if not backend.ensure_admin_rights():
        return
    if not backend._install_launcher_if_needed():
        return

    window = LauncherWindow()
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
