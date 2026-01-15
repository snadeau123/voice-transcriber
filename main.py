#!/usr/bin/env python3

import os
import sys
import tempfile
import threading
import subprocess
import signal
from datetime import datetime

import httpx
from dotenv import load_dotenv
from pynput import keyboard

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTextEdit, QSystemTrayIcon, QMenu
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt6.QtGui import QIcon, QAction, QFont

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
WHISPER_MODEL = os.getenv("WHISPER_MODEL_GROQ", "whisper-large-v3-turbo")
LLM_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

TOGGLE_HOTKEY = {keyboard.Key.cmd, keyboard.KeyCode.from_char('h')}


class SignalBridge(QObject):
    recording_started = pyqtSignal()
    recording_stopped = pyqtSignal(str)
    transcription_done = pyqtSignal(str)
    cleanup_done = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    status_update = pyqtSignal(str)
    hotkey_toggle = pyqtSignal()


class AudioRecorder:
    def __init__(self):
        self.recording = False
        self.process = None
        self.output_file = None

    def start(self):
        self.recording = True
        self.output_file = tempfile.NamedTemporaryFile(
            suffix=".wav", delete=False, prefix="voice_"
        )
        self.output_file.close()
        self.process = subprocess.Popen(
            [
                "parecord",
                "--format=s16le",
                "--rate=16000",
                "--channels=1",
                "--file-format=wav",
                self.output_file.name
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

    def stop(self) -> str:
        self.recording = False
        if self.process:
            self.process.send_signal(signal.SIGINT)
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.process = None
        if self.output_file and os.path.exists(self.output_file.name):
            if os.path.getsize(self.output_file.name) > 44:
                return self.output_file.name
            else:
                os.unlink(self.output_file.name)
        return ""


class GroqAPI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = httpx.Client(timeout=120.0)

    def transcribe(self, audio_path: str) -> str:
        url = "https://api.groq.com/openai/v1/audio/transcriptions"
        with open(audio_path, "rb") as f:
            files = {"file": ("audio.wav", f, "audio/wav")}
            data = {"model": WHISPER_MODEL}
            headers = {"Authorization": f"Bearer {self.api_key}"}
            response = self.client.post(url, files=files, data=data, headers=headers)
            response.raise_for_status()
            result = response.json()
            return result.get("text", "")

    def cleanup(self, text: str) -> str:
        url = "https://api.groq.com/openai/v1/chat/completions"
        system_prompt = """Your goal is to take user prompt, which has been transcribed from a voice recording, and clean up the structure if the flow is disjointed,or has too much repetition. Make sure you don't lose any information in the process, everything that was mentioned must end up in the final text, even it its reorganized for clarity. But don't add extra information either, your goal is just to make it more clear. Keep a fairly conversational tone, don't expend on the text by giving example or making plans or anything beyond what the initial recording states."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": LLM_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Here is the user prompt: {text}"}
            ],
            "max_tokens": 2000,
            "temperature": 0.7
        }
        response = self.client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        result = response.json()
        return result["choices"][0]["message"]["content"]


class TranscriberWindow(QMainWindow):
    def __init__(self, signals: SignalBridge):
        super().__init__()
        self.signals = signals
        self.recorder = AudioRecorder()
        self.api = GroqAPI(GROQ_API_KEY)
        self.current_audio_path = ""
        self.recording_start_time = None
        self.setup_ui()
        self.setup_signals()
        self.setup_timer()

    def setup_ui(self):
        self.setWindowTitle("Voice Transcriber")
        self.setFixedSize(500, 400)
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        self.status_label = QLabel("Ready - Press Win+H to record")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setFont(QFont("sans-serif", 11))
        layout.addWidget(self.status_label)

        self.timer_label = QLabel("00:00")
        self.timer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timer_label.setFont(QFont("monospace", 24, QFont.Weight.Bold))
        self.timer_label.setStyleSheet("color: #666;")
        layout.addWidget(self.timer_label)

        self.record_btn = QPushButton("Start Recording")
        self.record_btn.setMinimumHeight(50)
        self.record_btn.setFont(QFont("sans-serif", 12))
        self.record_btn.clicked.connect(self.toggle_recording)
        layout.addWidget(self.record_btn)

        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("Transcription will appear here...")
        self.text_edit.setFont(QFont("sans-serif", 10))
        layout.addWidget(self.text_edit, stretch=1)

        btn_layout = QHBoxLayout()
        self.copy_btn = QPushButton("Copy")
        self.copy_btn.clicked.connect(self.copy_text)
        self.copy_btn.setEnabled(False)
        btn_layout.addWidget(self.copy_btn)

        self.cleanup_btn = QPushButton("Clean Up")
        self.cleanup_btn.clicked.connect(self.cleanup_text)
        self.cleanup_btn.setEnabled(False)
        btn_layout.addWidget(self.cleanup_btn)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.clear_text)
        btn_layout.addWidget(self.clear_btn)

        layout.addLayout(btn_layout)

        hint = QLabel("Win+H: Toggle Recording")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet("color: #888; font-size: 9px;")
        layout.addWidget(hint)

    def setup_signals(self):
        self.signals.recording_started.connect(self.on_recording_started)
        self.signals.recording_stopped.connect(self.on_recording_stopped)
        self.signals.transcription_done.connect(self.on_transcription_done)
        self.signals.cleanup_done.connect(self.on_cleanup_done)
        self.signals.error_occurred.connect(self.on_error)
        self.signals.status_update.connect(self.update_status)
        self.signals.hotkey_toggle.connect(self.toggle_recording)

    def setup_timer(self):
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_timer)

    def toggle_recording(self):
        if self.recorder.recording:
            self.stop_recording()
        else:
            self.start_recording()

    def start_recording(self):
        try:
            self.recorder.start()
            self.recording_start_time = datetime.now()
            self.timer.start(100)
            self.signals.recording_started.emit()
        except Exception as e:
            self.signals.error_occurred.emit(f"Failed to start recording: {e}")

    def stop_recording(self):
        self.timer.stop()
        def do_stop():
            try:
                audio_path = self.recorder.stop()
                self.signals.recording_stopped.emit(audio_path)
                if audio_path:
                    self.signals.status_update.emit("Transcribing...")
                    text = self.api.transcribe(audio_path)
                    self.signals.transcription_done.emit(text)
                    try:
                        os.unlink(audio_path)
                    except:
                        pass
            except Exception as e:
                self.signals.error_occurred.emit(f"Error: {e}")
        threading.Thread(target=do_stop, daemon=True).start()

    def update_timer(self):
        if self.recording_start_time:
            elapsed = datetime.now() - self.recording_start_time
            minutes = int(elapsed.total_seconds() // 60)
            seconds = int(elapsed.total_seconds() % 60)
            self.timer_label.setText(f"{minutes:02d}:{seconds:02d}")

    def on_recording_started(self):
        self.record_btn.setText("Stop Recording")
        self.record_btn.setStyleSheet("background-color: #ff4444; color: white;")
        self.status_label.setText("Recording...")
        self.timer_label.setStyleSheet("color: #ff4444;")
        self.show()
        self.activateWindow()
        self.raise_()

    def on_recording_stopped(self, audio_path: str):
        self.record_btn.setText("Start Recording")
        self.record_btn.setStyleSheet("")
        self.timer_label.setStyleSheet("color: #666;")

    def on_transcription_done(self, text: str):
        self.text_edit.setText(text)
        self.copy_btn.setEnabled(bool(text))
        self.cleanup_btn.setEnabled(bool(text))
        self.status_label.setText("Transcription complete")

    def on_cleanup_done(self, text: str):
        self.text_edit.setText(text)
        self.status_label.setText("Text cleaned up")

    def on_error(self, message: str):
        self.status_label.setText(f"Error: {message}")
        self.record_btn.setText("Start Recording")
        self.record_btn.setStyleSheet("")

    def update_status(self, message: str):
        self.status_label.setText(message)

    def copy_text(self):
        text = self.text_edit.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.status_label.setText("Copied to clipboard")

    def cleanup_text(self):
        text = self.text_edit.toPlainText()
        if not text:
            return
        self.cleanup_btn.setEnabled(False)
        self.status_label.setText("Cleaning up...")
        def do_cleanup():
            try:
                cleaned = self.api.cleanup(text)
                self.signals.cleanup_done.emit(cleaned)
            except Exception as e:
                self.signals.error_occurred.emit(f"Cleanup failed: {e}")
            finally:
                self.cleanup_btn.setEnabled(True)
        threading.Thread(target=do_cleanup, daemon=True).start()

    def clear_text(self):
        self.text_edit.clear()
        self.copy_btn.setEnabled(False)
        self.cleanup_btn.setEnabled(False)
        self.timer_label.setText("00:00")
        self.status_label.setText("Ready - Press Win+H to record")


class GlobalHotkeyListener:
    def __init__(self, signals: SignalBridge, window: TranscriberWindow):
        self.signals = signals
        self.window = window
        self.current_keys = set()
        self.listener = None
        self.hotkey_fired = False

    def start(self):
        self.listener = keyboard.Listener(
            on_press=self.on_press,
            on_release=self.on_release
        )
        self.listener.start()

    def stop(self):
        if self.listener:
            self.listener.stop()

    def on_press(self, key):
        try:
            if hasattr(key, 'char') and key.char:
                self.current_keys.add(keyboard.KeyCode.from_char(key.char.lower()))
            else:
                self.current_keys.add(key)
        except:
            self.current_keys.add(key)
        if self._check_hotkey(TOGGLE_HOTKEY):
            if not self.hotkey_fired:
                self.hotkey_fired = True
                self.signals.hotkey_toggle.emit()

    def on_release(self, key):
        try:
            if hasattr(key, 'char') and key.char:
                self.current_keys.discard(keyboard.KeyCode.from_char(key.char.lower()))
            else:
                self.current_keys.discard(key)
        except:
            pass
        if not self._check_hotkey(TOGGLE_HOTKEY):
            self.hotkey_fired = False

    def _check_hotkey(self, target_keys: set) -> bool:
        normalized = set()
        for k in self.current_keys:
            if isinstance(k, keyboard.KeyCode):
                normalized.add(k)
            elif k in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r, keyboard.Key.ctrl):
                normalized.add(keyboard.Key.ctrl_l)
            elif k in (keyboard.Key.shift_l, keyboard.Key.shift_r, keyboard.Key.shift):
                normalized.add(keyboard.Key.shift)
            elif k in (keyboard.Key.cmd_l, keyboard.Key.cmd_r, keyboard.Key.cmd):
                normalized.add(keyboard.Key.cmd)
            else:
                normalized.add(k)
        target_normalized = set()
        for k in target_keys:
            if isinstance(k, keyboard.KeyCode):
                target_normalized.add(k)
            elif k in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r, keyboard.Key.ctrl):
                target_normalized.add(keyboard.Key.ctrl_l)
            elif k in (keyboard.Key.shift_l, keyboard.Key.shift_r, keyboard.Key.shift):
                target_normalized.add(keyboard.Key.shift)
            elif k in (keyboard.Key.cmd_l, keyboard.Key.cmd_r, keyboard.Key.cmd):
                target_normalized.add(keyboard.Key.cmd)
            else:
                target_normalized.add(k)
        return target_normalized.issubset(normalized)


class SystemTrayApp:
    def __init__(self, app: QApplication, window: TranscriberWindow):
        self.app = app
        self.window = window
        self.tray = QSystemTrayIcon()
        self.setup_tray()

    def setup_tray(self):
        from PyQt6.QtGui import QPixmap, QPainter, QColor
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setBrush(QColor("#4CAF50"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(4, 4, 24, 24)
        painter.end()
        self.tray.setIcon(QIcon(pixmap))
        self.tray.setToolTip("Voice Transcriber")
        menu = QMenu()
        show_action = QAction("Show Window", menu)
        show_action.triggered.connect(self.show_window)
        menu.addAction(show_action)
        record_action = QAction("Start Recording", menu)
        record_action.triggered.connect(self.window.start_recording)
        menu.addAction(record_action)
        menu.addSeparator()
        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self.quit_app)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.on_tray_activated)
        self.tray.show()

    def show_window(self):
        self.window.show()
        self.window.activateWindow()
        self.window.raise_()

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_window()

    def quit_app(self):
        self.tray.hide()
        self.app.quit()


def main():
    if not GROQ_API_KEY:
        print("Error: GROQ_API_KEY not set in environment or .env file")
        sys.exit(1)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    signals = SignalBridge()
    window = TranscriberWindow(signals)
    tray = SystemTrayApp(app, window)
    hotkey_listener = GlobalHotkeyListener(signals, window)
    hotkey_listener.start()
    window.show()
    print("Voice Transcriber started! Hotkey: Win+H")
    try:
        sys.exit(app.exec())
    finally:
        hotkey_listener.stop()


if __name__ == "__main__":
    main()
