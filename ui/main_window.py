"""
ui/main_window.py
Top-level window: sidebar + left panel + content area, all wired together.
"""

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QSplitter,
    QStatusBar, QLabel, QProgressBar
)
import json
import os

from PySide6.QtCore import Qt, QThreadPool, QSettings, QTimer

from ui.sidebar      import Sidebar
from ui.panel_left   import LeftPanel, DRIVES_MARKER
from ui.panel_gallery import GalleryPanel
from ui.theme        import DARK_THEME


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("GalleryAIPro", "Gallery AI Pro")
        self._locked_left_width = 240
        self._restoring_state = False
        self.setWindowTitle("Gallery AI Pro")
        self.setMinimumSize(1100, 680)
        self.resize(1400, 860)
        self.setStyleSheet(DARK_THEME)

        # Timer untuk debounced autosave (2 detik setelah perubahan terakhir)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._save_window_state)

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

        bar.addWidget(self.lbl_count)
        bar.addWidget(QLabel("  ·  "))
        bar.addWidget(self.lbl_tagged)
        bar.addPermanentWidget(self.lbl_msg)

    # ── Wire signals ─────────────────────────────
    def _wire_signals(self):
        # Sidebar nav → switch content panel
        self.sidebar.nav_changed.connect(self.content.show_section)
        self.sidebar.nav_changed.connect(
            lambda s: self.lbl_msg.setText(s.capitalize()))

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
                if last_loc == DRIVES_MARKER or os.path.isdir(last_loc):
                    self.content.gallery.load_folder(last_loc, _push=False)

        self._restoring_state = False

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

        # Placeholder panels for sections not yet built
        self._ph: dict[str, QWidget] = {}
        for name in ["timeline","search","face","map","duplicates","stats","settings"]:
            w = self._placeholder(name)
            self._ph[name] = w
            layout.addWidget(w)
            w.setVisible(False)

        self._current = "gallery"

    def _placeholder(self, name: str) -> QWidget:
        w = QWidget()
        from PySide6.QtWidgets import QVBoxLayout
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
        elif self._current in self._ph:
            self._ph[self._current].setVisible(False)

        # Show new
        if name == "gallery":
            self.gallery.setVisible(True)
        elif name in self._ph:
            self._ph[name].setVisible(True)
        else:
            # Unknown — show gallery as fallback
            self.gallery.setVisible(True)
            name = "gallery"

        self._current = name
