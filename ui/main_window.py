"""
ui/main_window.py
Top-level window: sidebar + left panel + content area, all wired together.
"""

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QSplitter,
    QStatusBar, QLabel, QProgressBar, QFormLayout, QComboBox, QGroupBox,
    QLineEdit, QCheckBox, QPushButton, QMessageBox
)
import json
import os
import time

from PySide6.QtCore import Qt, QThreadPool, QSettings, QTimer, Signal, QRunnable, QObject

from ui.sidebar       import Sidebar
from ui.panel_left    import LeftPanel, DRIVES_MARKER
from ui.panel_gallery  import GalleryPanel
from ui.panel_map      import MapPanel
from ui.theme         import get_stylesheet


class GeocodeSignals(QObject):
    """Signals for thread-safe UI updates from GeocodeWorker."""
    status_changed = Signal(str, bool)  # (text, visible)
    finished = Signal()                 # signal to clear running flag

class GeocodeWorker(QRunnable):
    """Worker untuk memproses geocoding di latar belakang."""
    def __init__(self, force=False, photo_ids=None):
        super().__init__()
        self.signals = GeocodeSignals()
        self.force = force
        self.photo_ids = photo_ids # Filter ID spesifik dari peta
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            from core.database import get_photos_needing_geocode, update_photo_address
            from core.geocoder import reverse_geocode, get_delay_needed, HAS_GEOPY
            
            settings = QSettings("GalleryAIPro", "Gallery AI Pro")
            mode = settings.value("api/gps_mode", "Offline (Cepat, Privat)")

            photos = get_photos_needing_geocode(mode, photo_ids=self.photo_ids)
            if not photos or len(photos) == 0:
                if self._is_cancelled:
                    return
                
                if self.force:
                    self.signals.status_changed.emit("ℹ️ Tidak ada foto yang perlu dipindai di area ini", True)
                    time.sleep(2)
                return

            # Initialize geolocator once for the entire batch (Policy compliance)
            geolocator = None
            if HAS_GEOPY:
                from geopy.geocoders import Nominatim
                geolocator = Nominatim(user_agent="GalleryAIPro_v4")

            # Update UI via signals (Thread-safe)
            msg_start = "📍 Memindai manual..." if self.force else "📍 Mencari alamat..."
            self.signals.status_changed.emit(msg_start, True)

            for p in photos:
                if self._is_cancelled: break
                
                # Cek apakah fitur dimatikan di tengah jalan (hanya jika bukan dijalankan manual/force)
                settings.sync()
                if not self.force and settings.value("api/auto_geocode", "true") == "false":
                    print("[GeocodeWorker] Auto-geocode dinonaktifkan. Menghentikan batch.")
                    break

                try:
                    addr = reverse_geocode(p['gps_lat'], p['gps_lng'], geolocator=geolocator)
                except Exception as e:
                    if "429" in str(e):
                        print("[GeocodeWorker] Rate limit 429 reached. Aborting batch.")
                        self.signals.status_changed.emit("⚠️ Limit API tercapai", True)
                        return
                    raise e

                if self._is_cancelled: break
                update_photo_address(p['id'], addr['country'], addr['city'], addr['district'], mode)
                
                delay = get_delay_needed()
                if delay > 0:
                    # Pecah sleep agar worker responsif terhadap pembatalan
                    for _ in range(int(delay * 10)):
                        if self._is_cancelled: break
                        time.sleep(0.1)

            # Jika pindaian manual selesai, beri konfirmasi sejenak
            if self.force and not self._is_cancelled:
                self.signals.status_changed.emit("✅ Selesai pindai manual", True)
                time.sleep(2)

        except Exception as e:
            print(f"[GeocodeWorker] Error during background processing: {e}")
        finally:
            # Ensure status is hidden even if an error occurs
            time.sleep(1)
            self.signals.status_changed.emit("", False)
            self.signals.finished.emit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("GalleryAIPro", "Gallery AI Pro")
        self._locked_left_width = 240
        self._restoring_state = False
        self._active_geocode_worker = None
        self._geocode_running = False
        self.setWindowTitle("Gallery AI Pro")
        self.setMinimumSize(1100, 680)
        self.resize(1400, 860)

        # Default ke tema System (Mengikuti Windows Explorer)
        self.current_theme = self.settings.value("window/theme", "System")
        self.setStyleSheet(get_stylesheet(self.current_theme))

        # Timer untuk debounced autosave (2 detik setelah perubahan terakhir)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save_window_state)
        
        # Timer untuk cek geocoding berkala (tiap 30 detik)
        self._geocode_timer = QTimer(self)
        self._geocode_timer.timeout.connect(self._trigger_geocoding)
        self._geocode_timer.start(30000)

        self._build_ui()
        self._build_statusbar()
        self._wire_signals()
        QTimer.singleShot(0, self._restore_window_state)

    # ── Layout ───────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Far-left sidebar (nav icons)
        self.sidebar = Sidebar()
        self.sidebar.setObjectName("sidebar")
        root.addWidget(self.sidebar)

        # Horizontal splitter: left panel | content
        self.h_split = QSplitter(Qt.Orientation.Horizontal)
        self.h_split.setHandleWidth(1)
        self.h_split.setChildrenCollapsible(False)
        root.addWidget(self.h_split)

        # Left panel (folder tree + preview)
        self.left_panel = LeftPanel()
        self.left_panel.setObjectName("leftPanel")
        self.left_panel.setMinimumWidth(180)
        self.h_split.addWidget(self.left_panel)

        # Right: stacked content panels
        self.content = ContentStack()
        self.h_split.addWidget(self.content)

        self.h_split.setSizes([240, 1160])
        # Left panel fixed — only right panel grows when window is resized
        self.h_split.setStretchFactor(0, 0)
        self.h_split.setStretchFactor(1, 1)
        self._locked_left_width = self.h_split.sizes()[0]

    def _build_statusbar(self):
        bar = QStatusBar()
        self.setStatusBar(bar)

        self.lbl_count  = QLabel("0 foto")
        self.lbl_count.setObjectName("labelMuted")
        self.lbl_tagged = QLabel("0 ditag")
        self.lbl_tagged.setObjectName("labelMuted")
        self.lbl_msg    = QLabel("")
        self.lbl_msg.setObjectName("labelMuted")
        
        # Notifikasi Kecil Geocoding (Pojok kanan bawah)
        self.lbl_geocode_status = QLabel("")
        self.lbl_geocode_status.setStyleSheet("color: #a78bfa; font-size: 10px; font-weight: bold; margin-right: 10px;")
        self.lbl_geocode_status.setVisible(False)

        bar.addWidget(self.lbl_count)
        bar.addWidget(QLabel("  ·  "))
        bar.addWidget(self.lbl_tagged)
        
        bar.addPermanentWidget(self.lbl_geocode_status)
        bar.addPermanentWidget(self.lbl_msg)

    # ── Wire signals ─────────────────────────────
    def _wire_signals(self):
        # Sidebar nav → switch content panel
        self.sidebar.nav_changed.connect(self.content.show_section)
        self.sidebar.nav_changed.connect(
            lambda s: self.lbl_msg.setText(s.capitalize()))

        # Trigger refresh peta saat navigasi ke section map
        self.sidebar.nav_changed.connect(
            lambda s: self.content.map_panel.refresh_data(fit_bounds=True) if s == "map" else None
        )

        # Manual geocode trigger from Map Panel
        self.content.map_panel.geocode_requested.connect(lambda ids: self._trigger_geocoding(force=True, photo_ids=ids))

        # Folder tree click → load gallery
        self.left_panel.folder_selected.connect(
            self.content.gallery.load_folder)

        # Gallery photo hover → left panel preview
        self.content.gallery.photo_selected.connect(
            self.left_panel.show_preview)
        self.content.gallery.location_changed.connect(
            self.left_panel.sync_to_path)
        self.content.gallery.location_changed.connect(self._request_autosave)
        self.content.gallery.state_changed.connect(self._request_autosave)

        # Gallery stats → statusbar
        self.content.gallery.stats_changed.connect(self._update_stats)
        self.h_split.splitterMoved.connect(self._on_h_splitter_moved)
        self.h_split.splitterMoved.connect(self._request_autosave)

    def _trigger_geocoding(self, force=False, photo_ids=None):
        """Mulai proses geocoding jika diizinkan di setting."""
        if self._geocode_running:
            # Beri tahu user jika proses manual sedang antre/berjalan
            if force:
                self._update_geocode_status("⏳ Sedang memproses...", True)
            return
            
        self.settings.sync()
        if force and photo_ids is not None:
            print(f"[MainWindow] Memproses pindai manual untuk {len(photo_ids)} foto di area zoom. Mode: {self.settings.value('api/gps_mode')}")
            
        auto = self.settings.value("api/auto_geocode", "true") == "true"
        if auto or force:
            self._active_geocode_worker = GeocodeWorker(force=force, photo_ids=photo_ids)
            self._active_geocode_worker.signals.status_changed.connect(self._update_geocode_status)
            self._active_geocode_worker.signals.finished.connect(self._on_geocode_finished)
            self._geocode_running = True
            QThreadPool.globalInstance().start(self._active_geocode_worker)

    def _on_geocode_finished(self):
        self._active_geocode_worker = None
        self._geocode_running = False
        # Jika sedang di panel peta, refresh datanya agar filter muncul
        if self.content._current == "map":
            self.content.map_panel.refresh_data(fit_bounds=False) # Kunci zoom

    def _update_geocode_status(self, text: str, visible: bool):
        self.lbl_geocode_status.setText(text)
        self.lbl_geocode_status.setVisible(visible)

    def change_theme(self, theme_name: str):
        """Update application theme globally."""
        self.current_theme = theme_name
        self.setStyleSheet(get_stylesheet(theme_name))
        self.settings.setValue("window/theme", theme_name)
        # Re-polish sidebar buttons if needed
        self.sidebar._set_active(self.sidebar._active)

    def _update_stats(self, total: int, tagged: int):
        self.lbl_count.setText(f"{total} foto")
        self.lbl_tagged.setText(f"{tagged} ditag")

    def _request_autosave(self):
        if not self._restoring_state:
            self._save_timer.start(2000)

    def _restore_window_state(self):
        self._restoring_state = True
        geometry = self.settings.value("window/geometry")
        if geometry:
            self.restoreGeometry(geometry)

        left_width = self.settings.value("window/left_panel_width")
        if left_width is not None:
            self._locked_left_width = int(left_width)

        h_sizes = self.settings.value("window/h_split_sizes", [])
        if h_sizes:
            self.h_split.setSizes([int(v) for v in h_sizes])
        total = sum(self.h_split.sizes())
        if total > 0:
            left = max(self.left_panel.minimumWidth(),
                       min(self._locked_left_width, total - 200))
            self.h_split.setSizes([left, max(200, total - left)])
            self._locked_left_width = left

        v_sizes = self.settings.value("window/v_split_sizes", [])
        if v_sizes:
            self.left_panel.v_splitter.setSizes([int(v) for v in v_sizes])

        last_section = self.settings.value("window/last_section", "gallery")
        if isinstance(last_section, str):
            self.content.show_section(last_section)
            self.sidebar._set_active(last_section)
            self.lbl_msg.setText(last_section.capitalize())

        tree_state_raw = self.settings.value("window/left_tree_state", "")
        if isinstance(tree_state_raw, str) and tree_state_raw:
            try:
                self.left_panel.restore_tree_state(json.loads(tree_state_raw))
            except (TypeError, json.JSONDecodeError):
                pass

        gallery_state_raw = self.settings.value("window/gallery_state", "")
        restored_via_state = False
        if isinstance(gallery_state_raw, str) and gallery_state_raw:
            try:
                self.content.gallery.restore_state(json.loads(gallery_state_raw))
                restored_via_state = True
            except (TypeError, json.JSONDecodeError):
                pass

        # Jika tidak berhasil dipulihkan via state, coba via last_location sebagai cadangan
        if not restored_via_state:
            last_loc = self.settings.value("window/last_location")
            if isinstance(last_loc, str) and last_loc:
                if last_loc in (DRIVES_MARKER, DRIVES_MARKER.replace("drives", "quick_access")) or os.path.isdir(last_loc):
                    self.content.gallery.load_folder(last_loc, _push=False)

        # Sidebar & Content wiring
        self.content.settings_panel.theme_changed.connect(self.change_theme)
        self.content.settings_panel.gps_reset_requested.connect(self._handle_gps_reset)

        self._restoring_state = False

    def _handle_gps_reset(self, mode):
        """Menangani permintaan reset alamat dari SettingsPanel."""
        from core.database import reset_photo_addresses
        reset_photo_addresses(mode)
        # Paksa refresh panel peta agar filter 'Unknown' segera muncul
        self.content.map_panel.refresh_data()
        QMessageBox.information(self, "Selesai", f"Data alamat {mode} telah direset. Peta telah diperbarui.")

    def _save_window_state(self):
        if self._restoring_state: return  # Jangan simpan saat sedang loading
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/h_split_sizes", self.h_split.sizes())
        self.settings.setValue("window/left_panel_width", self._locked_left_width)
        self.settings.setValue("window/v_split_sizes", self.left_panel.v_splitter.sizes())
        self.settings.setValue("window/last_section", getattr(self.sidebar, "_active", "gallery"))
        self.settings.setValue("window/last_location", self._current_location())
        self.settings.setValue("window/left_tree_state", json.dumps(self.left_panel.export_tree_state()))
        self.settings.setValue("window/gallery_state", json.dumps(self.content.gallery.export_state()))

    def _current_location(self) -> str:
        gallery = self.content.gallery
        if getattr(gallery, "_is_drives_view", False):
            return DRIVES_MARKER
        if getattr(gallery, "_is_quick_access_view", False):
            return DRIVES_MARKER.replace("drives", "quick_access")
        return gallery.current_folder or ""

    def _on_h_splitter_moved(self, pos: int, index: int):
        if self._restoring_state:
            return
        self._locked_left_width = self.h_split.sizes()[0]

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._restoring_state:
            return
        total = sum(self.h_split.sizes())
        if total <= 0:
            return
        min_right = 200
        left = max(self.left_panel.minimumWidth(),
                   min(self._locked_left_width, total - min_right))
        self.h_split.setSizes([left, max(min_right, total - left)])

    def closeEvent(self, event):
        """
        Properly shut down background threads before closing.
        Without this, QThreadPool workers keep the process alive
        and the terminal stays open after the window is closed.
        """
        # Cancel any running folder scan
        gallery = self.content.gallery
        if gallery._scanner:
            gallery._scanner.cancel()

        # Batalkan geocoding yang sedang berjalan
        if self._active_geocode_worker:
            self._active_geocode_worker.cancel()

        # Cancel all pending thumbnail workers
        gallery.thumb_loader.pool.clear()

        # Wait for all active threads to finish (max 3 seconds)
        QThreadPool.globalInstance().waitForDone(3000)

        self._save_window_state()
        event.accept()


# ── Content stack ────────────────────────────────
class ContentStack(QWidget):
    """Shows one panel at a time based on sidebar selection."""

    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Real panels
        self.gallery = GalleryPanel()
        layout.addWidget(self.gallery)

        self.settings_panel = SettingsPanel()
        layout.addWidget(self.settings_panel)
        self.settings_panel.setVisible(False)
        
        self.map_panel = MapPanel()
        layout.addWidget(self.map_panel)
        self.map_panel.setVisible(False)

        # Placeholder panels for sections not yet built
        self._ph: dict[str, QWidget] = {}
        for name in ["timeline","search","face","duplicates","stats"]:
            w = self._placeholder(name)
            self._ph[name] = w
            layout.addWidget(w)
            w.setVisible(False)

        self._current = "gallery"

    def _placeholder(self, name: str) -> QWidget:
        w = QWidget()
        L = QVBoxLayout(w)
        L.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_map = {
            "timeline":"🕐","search":"🔍","face":"👤","map":"🗺️",
            "duplicates":"📋","stats":"📊","settings":"⚙️"
        }
        lbl = QLabel(f"{icon_map.get(name,'📌')}  Panel '{name}'\n— segera hadir —")
        lbl.setObjectName("labelMuted")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("font-size:16px; line-height:2;")
        L.addWidget(lbl)
        return w

    def show_section(self, name: str):
        # Hide current
        if self._current == "gallery":
            self.gallery.setVisible(False)
        elif self._current == "settings":
            self.settings_panel.setVisible(False)
        elif self._current == "map":
            self.map_panel.setVisible(False)
        elif self._current in self._ph:
            self._ph[self._current].setVisible(False)

        # Show new
        if name == "gallery":
            self.gallery.setVisible(True)
        elif name == "settings":
            self.settings_panel.setVisible(True)
        elif name == "map":
            self.map_panel.setVisible(True)
        elif name in self._ph:
            self._ph[name].setVisible(True)
        else:
            # Unknown — show gallery as fallback
            self.gallery.setVisible(True)
            name = "gallery"

        self._current = name


class SettingsPanel(QWidget):
    """Real settings panel to manage API Keys and Themes."""
    theme_changed = Signal(str)
    gps_reset_requested = Signal(str)

    def __init__(self):
        super().__init__()
        
        L = QVBoxLayout(self)
        L.setContentsMargins(40, 40, 40, 40)
        L.setAlignment(Qt.AlignmentFlag.AlignTop)

        title = QLabel("⚙️  Pengaturan")
        title.setStyleSheet("font-size: 24px; font-weight: 700; margin-bottom: 20px;")
        L.addWidget(title)

        # Appearance Group
        group = QGroupBox("Tampilan")
        FL = QFormLayout(group)
        FL.setContentsMargins(20, 20, 20, 20)
        FL.setSpacing(15)

        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["System", "Windows Light", "Windows Dark", "Slate Classic", "Astro Dark"])
        
        settings = QSettings("GalleryAIPro", "Gallery AI Pro")
        saved_theme = settings.value("window/theme", "Astro Dark")
        self.theme_combo.setCurrentText(saved_theme)
        
        self.theme_combo.currentTextChanged.connect(self.theme_changed.emit)
        
        FL.addRow("Tema Aplikasi:", self.theme_combo)
        L.addWidget(group)

        # AI API Keys Group
        ai_group = QGroupBox("API Keys AI")
        AIL = QFormLayout(ai_group)
        AIL.setContentsMargins(20, 20, 20, 20)
        AIL.setSpacing(15)

        self.key_gemini = QLineEdit()
        self.key_gemini.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_gemini.setPlaceholderText("AIzaSy...")
        self.key_gemini.setText(settings.value("api/gemini", ""))
        self.key_gemini.textChanged.connect(lambda t: settings.setValue("api/gemini", t))

        self.key_openai = QLineEdit()
        self.key_openai.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_openai.setPlaceholderText("sk-...")
        self.key_openai.setText(settings.value("api/openai", ""))
        self.key_openai.textChanged.connect(lambda t: settings.setValue("api/openai", t))

        AIL.addRow("Google Gemini Key:", self.key_gemini)
        AIL.addRow("OpenAI API Key:", self.key_openai)
        
        help_lbl = QLabel("API Key disimpan secara lokal di komputer ini.")
        help_lbl.setStyleSheet("font-size: 10px; color: #5a5a90; margin-top: 5px;")
        AIL.addRow("", help_lbl)

        L.addWidget(ai_group)

        # GPS & Location Group
        gps_group = QGroupBox("Lokasi & Peta")
        GL = QFormLayout(gps_group)
        self.gps_mode = QComboBox()
        self.gps_mode.addItems(["Offline (Cepat, Privat)", "Online (Detail, Butuh Internet)"])
        saved_gps = settings.value("api/gps_mode", "Offline (Cepat, Privat)")
        self.gps_mode.setCurrentText(saved_gps)
        self.gps_mode.currentTextChanged.connect(lambda t: settings.setValue("api/gps_mode", t))
        
        self.cb_auto_geocode = QCheckBox("Geocoding Otomatis di Latar Belakang")
        is_auto = settings.value("api/auto_geocode", "true") == "true"
        self.cb_auto_geocode.setChecked(is_auto)
        self.cb_auto_geocode.toggled.connect(self._on_auto_geocode_toggled)

        GL.addRow("", self.cb_auto_geocode)
        GL.addRow("Mode Geocoding:", self.gps_mode)

        # Dual Maintenance Area (Offline & Online Reset)
        m_layout = QHBoxLayout()
        m_style = """
            QPushButton { 
                background: #3f3f46; border: none; padding: 8px; 
                border-radius: 4px; font-weight: bold; font-size: 11px;
            }
            QPushButton:hover { background: #52525b; }
        """
        self.btn_reset_off = QPushButton("🧹 Reset Offline")
        self.btn_reset_off.setStyleSheet(m_style + "QPushButton { color: #f87171; }")
        self.btn_reset_off.clicked.connect(lambda: self._confirm_reset_gps("Offline"))
        
        self.btn_reset_on = QPushButton("🌐 Reset Online")
        self.btn_reset_on.setStyleSheet(m_style + "QPushButton { color: #60a5fa; }")
        self.btn_reset_on.clicked.connect(lambda: self._confirm_reset_gps("Online"))

        m_layout.addWidget(self.btn_reset_off)
        m_layout.addWidget(self.btn_reset_on)
        GL.addRow("Maintenance:", m_layout)

        L.addWidget(gps_group)

        L.addStretch()

    def _on_auto_geocode_toggled(self, checked):
        settings = QSettings("GalleryAIPro", "Gallery AI Pro")
        settings.setValue("api/auto_geocode", "true" if checked else "false")
        settings.sync() # Paksa tulis ke disk agar terlihat oleh thread lain

    def _confirm_reset_gps(self, mode):
        msg = QMessageBox(self)
        msg.setWindowTitle(f"Reset Alamat {mode}")
        msg.setText(f"Hapus data alamat hasil pencarian {mode}?")
        msg.setInformativeText(f"Metadata lokasi {mode} akan dikosongkan. Koordinat GPS asli tidak akan berubah.")
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        
        if msg.exec() == QMessageBox.StandardButton.Yes:
            self.gps_reset_requested.emit(mode)
