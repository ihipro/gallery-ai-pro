"""
ui/panel_gallery.py  (fixed)

Fixes vs original:
  - load_folder always resets self.photos (no stale data from prev folder)
  - Gallery shows subfolders as navigable cards/rows
  - _on_photo_found updates UI after 1st, 2nd...10th photo, then every 5
  - View toggle buttons are mutually exclusive (QButtonGroup)
  - FolderScanWorker no longer blocks on thumbnail gen inside scan loop
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLineEdit, QComboBox, QLabel, QScrollArea,
    QGridLayout, QFrame, QSizePolicy,
    QToolButton, QDialog, QApplication, QProgressBar,
    QButtonGroup, QListView, QStyledItemDelegate, QStyle
)
from PySide6.QtCore import Qt, Signal, QTimer, QPoint, QAbstractListModel, QModelIndex, QSize, QRect
from PySide6.QtGui import QPixmap, QCursor, QKeyEvent, QPainter, QColor, QFont, QPen
from PySide6.QtWebChannel import QWebChannel
import os, math

from core.thumbnailer import ThumbLoader, FolderScanWorker, ScannerSignals
from core.database import (
    init_db, upsert_photo, get_photos_in_folder,
    update_tags, toggle_fav, get_stats
)

init_db()

# Map kategori tag ke warna CSS (sinkron dengan v4) 
TAG_COLORS = {
    'bg':          '#93c5fd', # tp-b (Blue)
    'ruang':       '#fdba74', # tp-ru (Orange)
    'detail_alam': '#5eead4', # tp-da (Teal)
    'waktu':       '#fdba74', # tp-w (Orange)
    'konten':      '#93c5fd', # tp-k (Blue)
    'tipe_foto':   '#c4b5fd', # tp-tf (Purple)
    'pose':        '#34d399', # tp-p (Green)
    'mood':        '#f9a8d4', # tp-m (Pink)
    'outfit':      '#fbbf24', # tp-o (Gold)
    'expr':        '#c4b5fd', # tp-e (Purple)
    'wilayah':     '#86efac', # tp-wl (Light Green)
    'destinasi':   '#67e8f9', # tp-ds (Cyan)
    'aktivitas':   '#fb923c', # tp-ak (Orange)
}

EMOJI_MAP = {
    'bg': {'alam':'🌿','pantai':'🏖️','kota':'🌆','interior':'🏠','studio':'🎨','kendaraan':'🚗','event':'🎤','lainnya':'📍'},
    'ruang': {'dapur':'🍳','ruang-tamu':'🛋️','kamar-tidur':'🛏️','kamar-mandi':'🚿'},
    'waktu': {'pagi':'🌅','siang':'☀️','sore':'🌇','malam':'🌙','golden-hour':'🌆'},
    'konten': {'manusia':'👤','kuliner':'🍽️','hewan':'🐾','arsitektur':'🏛️','dokumen':'📄','tanaman':'🌱','produk':'📦','screenshot':'🖥️','campuran':'🎯'},
    'pose': {'solo':'🧍','berdua':'👫','trio':'👥','grup':'🫂'},
    'mood': {'formal':'👗','kasual':'😊','performing':'🎶','candid':'📸','travelling':'✈️'}
}

class GalleryModel(QAbstractListModel):
    """Model data tunggal untuk menyimpan ribuan item (folder/foto)."""
    PathRole = Qt.ItemDataRole.UserRole + 1
    TypeRole = Qt.ItemDataRole.UserRole + 2  # 'f' folder, 'p' photo, 's' separator
    DataRole = Qt.ItemDataRole.UserRole + 3
    ThumbRole = Qt.ItemDataRole.UserRole + 4

    def __init__(self):
        super().__init__()
        self.items = [] # list of (type, data_dict_or_path)
        self.thumb_cache = {}

    def rowCount(self, parent=QModelIndex()):
        return len(self.items)

    def flags(self, index):
        if not index.isValid(): return Qt.ItemFlag.NoItemFlags
        item_type = self.items[index.row()][0]
        if item_type == 's':
            return Qt.ItemFlag.ItemIsEnabled # Aktif tapi tidak bisa dipilih (Selectable)
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid(): return None
        row = index.row()
        item_type, item_data = self.items[row]

        if role == self.TypeRole: return item_type
        if role == self.PathRole:
            return item_data if not isinstance(item_data, dict) else item_data.get('path')
        if role == self.DataRole: return item_data
        if role == self.ThumbRole:
            if item_type == 's': return None
            path = item_data if not isinstance(item_data, dict) else item_data.get('path')
            return self.thumb_cache.get(path)
        return None

    def update_thumb(self, path, thumb_path):
        for i, (it, idat) in enumerate(self.items):
            if it == 's': continue
            # Gunakan cara aman untuk mengambil path untuk perbandingan
            ipath = idat if not isinstance(idat, dict) else idat.get('path')
            if ipath == path:
                self.thumb_cache[path] = thumb_path
                idx = self.index(i)
                self.dataChanged.emit(idx, idx, [self.ThumbRole])
                break

    def set_items(self, new_items):
        self.beginResetModel()
        self.items = new_items
        self.endResetModel()

class GalleryDelegate(QStyledItemDelegate):
    """Melukis item secara manual (Virtual Rendering)."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.view_mode = "grid"

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        item_type = index.data(GalleryModel.TypeRole)
        path = index.data(GalleryModel.PathRole)
        rect = option.rect
        
        # Ambil warna dari palette untuk mendukung tema dinamis secara akurat
        palette = option.palette
        accent_color = palette.highlight().color()
        text_color = palette.windowText().color()
        muted_color = palette.placeholderText().color()
        
        # 1. Background (Highlight/Hover) - Hanya untuk folder dan foto
        if item_type != 's':
            is_sel = option.state & QStyle.StateFlag.State_Selected
            is_hover = option.state & QStyle.StateFlag.State_MouseOver
            
            if is_sel:
                bg_sel = QColor(accent_color)
                bg_sel.setAlpha(45) # Transparansi untuk background seleksi
                painter.fillRect(rect, bg_sel)
                painter.setPen(QPen(accent_color, 2))
                painter.drawRect(rect.adjusted(1,1,-1,-1))
            elif is_hover:
                bg_hover = QColor(text_color)
                bg_hover.setAlpha(15) # Efek hover halus menggunakan warna teks
                painter.fillRect(rect, bg_hover)

        # 2. Draw Content based on Type
        if item_type == 's': # Separator
            painter.setPen(muted_color)
            painter.setFont(QFont("DM Sans", 9, QFont.Weight.Bold))
            painter.drawText(rect.adjusted(10, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, str(path))
        
        elif item_type in ('f', 'd', 'p'):
            # Draw Thumbnail
            thumb_path = index.data(GalleryModel.ThumbRole)
            thumb_rect = rect.adjusted(10, 10, -10, -40) if self.view_mode == "grid" else QRect(rect.x()+5, rect.y()+5, 40, 40)
            
            if thumb_path:
                pix = QPixmap(thumb_path)
                if not pix.isNull():
                    # Skala gambar dengan mempertahankan rasio aspek asli agar tidak terlihat gepeng/tertarik
                    scaled_pix = pix.scaled(thumb_rect.size(), 
                                          Qt.AspectRatioMode.KeepAspectRatio, 
                                          Qt.TransformationMode.SmoothTransformation)
                    # Hitung koordinat agar gambar digambar tepat di tengah area thumb_rect
                    tx = thumb_rect.x() + (thumb_rect.width() - scaled_pix.width()) // 2
                    ty = thumb_rect.y() + (thumb_rect.height() - scaled_pix.height()) // 2
                    painter.drawPixmap(tx, ty, scaled_pix)
            else:
                # Placeholder
                # Background placeholder disesuaikan dengan kegelapan tema
                base_color = palette.base().color()
                placeholder_bg = base_color.lighter(120) if base_color.lightness() < 128 else base_color.darker(110)
                painter.fillRect(thumb_rect, placeholder_bg)
                
                painter.setPen(muted_color)
                icon = "📁" if item_type in ('f', 'd') else "🖼️"
                # Gunakan font yang lebih besar sesuai mode tampilan
                icon_font_size = 42 if self.view_mode == "grid" else 20
                painter.setFont(QFont("DM Sans", icon_font_size))
                painter.drawText(thumb_rect, Qt.AlignmentFlag.AlignCenter, icon)

            # Draw Text
            name = os.path.basename(path) if item_type != 'd' else path
            text_rect = rect.adjusted(5, rect.height()-30, -5, -5) if self.view_mode == "grid" else rect.adjusted(55, 0, -10, 0)
            if is_sel:
                # Jika tema terang (lightness > 128), gunakan warna teks gelap agar kontras dengan highlight transparan
                painter.setPen(text_color if palette.base().color().lightness() > 128 else palette.highlightedText().color())
            else:
                painter.setPen(muted_color)
            painter.setFont(QFont("DM Sans", 8))
            elided_name = painter.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, text_rect.width())
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter if self.view_mode == "grid" else Qt.AlignmentFlag.AlignVCenter, elided_name)
            
            # Draw AI/Fav Icons for photos
            if item_type == 'p':
                data = index.data(GalleryModel.DataRole)
                if data.get('fav'):
                    painter.drawText(rect.adjusted(0, 5, -5, 0), Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight, "⭐")
                if data.get('ai_tagged'):
                    painter.setBrush(accent_color)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.drawRoundedRect(QRect(rect.x()+5, rect.y()+5, 30, 14), 4, 4)
                    painter.setPen(Qt.PenStyle.SolidLine)
                    painter.setPen(QColor("white"))
                    painter.setFont(QFont("DM Sans", 7, QFont.Weight.Bold))
                    painter.drawText(QRect(rect.x()+5, rect.y()+5, 30, 14), Qt.AlignmentFlag.AlignCenter, "AI")

        painter.restore()

    def sizeHint(self, option, index):
        item_type = index.data(GalleryModel.TypeRole)
        if item_type == 's':
            # Gunakan lebar widget (QListView) agar separator menjadi baris penuh
            width = option.widget.width() if option.widget else 500
            return QSize(width - 40, 38)
        if self.view_mode == "grid":
            return QSize(170, 200)
        elif self.view_mode == "compact":
            return QSize(100, 120)
        return QSize(option.rect.width(), 50) # List mode


class GalleryPanel(QWidget):
    photo_selected = Signal(str)
    stats_changed  = Signal(int, int)
    location_changed = Signal(str)
    state_changed = Signal()
    GRID_CARD_WIDTH = 172
    COMPACT_CARD_WIDTH = 92

    def __init__(self):
        super().__init__()
        self.photos: list[dict] = []
        self._photo_paths_cache: set[str] = set()
        self.filtered: list[dict] = []
        self._subfolders: list[str] = []
        self.view_mode      = "grid"
        self.active_filter  = "all"
        self.hover_enabled  = True
        self.current_folder = None
        self._all_items: list[tuple] = []
        self._item_pos: dict[str, tuple] = {}   # path → (row, col) visual grid position
        self._sel_path: str | None = None
        self._nav_history: list[str] = []
        self._is_drives_view: bool = False   # True when showing drive list
        self._is_quick_access_view: bool = False
        self._scanner       = None
        self._scan_signals  = None
        self._scan_token    = 0
        self._view_btns: dict[str, QToolButton] = {}
        self._pending_restore_selection: str | None = None
        self._pending_restore_scroll: tuple[int, int] | None = None

        # Model-View Setup
        self.model = GalleryModel()
        self.delegate = GalleryDelegate(self)

        self.thumb_loader = ThumbLoader(self)
        # Loader sekarang update model, bukan widget card
        self.thumb_loader.thumb_ready.connect(self.model.update_thumb)
        self._progress_failsafe = QTimer(self)
        self._progress_failsafe.setSingleShot(True)
        self._progress_failsafe.timeout.connect(self._force_hide_progress)
        self._build()

    # ── Build ─────────────────────────────────────
    def _build(self):
        L = QVBoxLayout(self)
        L.setContentsMargins(0, 0, 0, 0); L.setSpacing(0)
        L.addWidget(self._build_toolbar())
        L.addWidget(self._build_progress())
        L.addWidget(self._build_filterbar())
        L.addWidget(self._build_scroll())

    def _build_toolbar(self):
        bar = QWidget(); bar.setObjectName("toolbar"); bar.setFixedHeight(48)
        L = QHBoxLayout(bar); L.setContentsMargins(12,6,12,6); L.setSpacing(6)

        self.btn_back = QPushButton("◀")
        self.btn_back.setToolTip("Kembali (Alt+←)")
        self.btn_back.setFixedWidth(32)
        self.btn_back.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_back.setEnabled(False)
        self.btn_back.clicked.connect(self._nav_back)
        L.addWidget(self.btn_back)

        self.btn_open = QPushButton("📁  Buka Folder")
        self.btn_open.setObjectName("btnPrimary")
        self.btn_open.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_open.clicked.connect(self._open_folder)
        L.addWidget(self.btn_open)

        self.btn_add = QPushButton("📂  Tambah Foto")
        self.btn_add.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_add.clicked.connect(self._add_files)
        L.addWidget(self.btn_add)

        self.btn_tag_all = QPushButton("✨  Auto-Tag Semua")
        self.btn_tag_all.setObjectName("btnAI")
        self.btn_tag_all.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_tag_all.setEnabled(False)
        L.addWidget(self.btn_tag_all)

        self.btn_tag_new = QPushButton("🤖  Yang Belum Ditag")
        self.btn_tag_new.setObjectName("btnAI")
        self.btn_tag_new.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_tag_new.setEnabled(False)
        L.addWidget(self.btn_tag_new)

        L.addStretch()

        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍  Cari nama foto...")
        self.search.setFixedWidth(200)
        # Autosave saat pencarian berhenti diketik (via state_changed)
        self.search.textChanged.connect(lambda: QTimer.singleShot(500, self.state_changed.emit))
        self.search.textChanged.connect(self._apply_filter)
        L.addWidget(self.search)

        self.sort_combo = QComboBox()
        self.sort_combo.addItems([
            "📥 Terbaru ditambahkan","📥 Terlama ditambahkan",
            "🔤 Nama A–Z","🔤 Nama Z–A",
            "📅 Tanggal (terbaru)","📅 Tanggal (lama)",
            "📦 Ukuran (terbesar)","📦 Ukuran (terkecil)",
            "🔤 Ekstensi (A–Z)","🔤 Ekstensi (Z–A)",
        ])
        self.sort_combo.currentIndexChanged.connect(self._apply_filter)
        self.sort_combo.currentIndexChanged.connect(self.state_changed)
        L.addWidget(self.sort_combo)

        # FIX: Mutually exclusive view buttons via QButtonGroup
        VSTYLE = ("QToolButton{background:#141425;border:1px solid #303050;"
                  "border-radius:5px;color:#5a5a90;font-size:14px;}"
                  "QToolButton:hover{border-color:#a78bfa;color:#e0e0f0;}"
                  "QToolButton:checked{background:#60a5fa;border-color:#60a5fa;color:#fff;}")
        self._view_group = QButtonGroup(self)
        self._view_group.setExclusive(True)
        for icon, mode, tip in [("⊞","grid","Grid"),("⊟","compact","Compact"),("☰","list","List")]:
            btn = QToolButton(); btn.setText(icon); btn.setToolTip(tip)
            btn.setCheckable(True); btn.setFixedSize(28,28)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.setStyleSheet(VSTYLE)
            btn.clicked.connect(lambda chk=False, m=mode: self._set_view(m))
            if mode == "grid": btn.setChecked(True)
            L.addWidget(btn)
            self._view_btns[mode] = btn
            self._view_group.addButton(btn)
        return bar

    def _build_progress(self):
        w = QWidget(); w.setFixedHeight(20); w.setObjectName("progressContainer")
        L = QHBoxLayout(w); L.setContentsMargins(12,2,12,2); L.setSpacing(8)
        self.prog_bar = QProgressBar(); self.prog_bar.setFixedHeight(3); self.prog_bar.setVisible(False)
        self.prog_lbl = QLabel(""); self.prog_lbl.setObjectName("labelMuted"); self.prog_lbl.setVisible(False)
        L.addWidget(self.prog_bar); L.addWidget(self.prog_lbl)
        return w

    def _build_filterbar(self):
        bar = QWidget(); bar.setObjectName("toolbar"); bar.setFixedHeight(36)
        L = QHBoxLayout(bar); L.setContentsMargins(12,4,12,4); L.setSpacing(6)
        lbl = QLabel("Filter:"); lbl.setObjectName("labelMuted"); L.addWidget(lbl)
        FSTYLE = ("QPushButton{background:transparent;border:1px solid #222235;"
                  "border-radius:12px;color:#5a5a90;font-size:11px;padding:0 10px;}"
                  "QPushButton:hover{border-color:#e0e0f0;color:#e0e0f0;}"
                  "QPushButton:checked{border-color:#a78bfa;"
                  "background:rgba(167,139,250,0.1);color:#c4b5fd;}")
        self.filter_btns: dict[str,QPushButton] = {}
        for key, label in [("all","Semua"),("untagged","⚪ Belum Ditag"),
                           ("tagged","✨ AI Tagged"),("fav","⭐ Favorit")]:
            btn = QPushButton(label); btn.setCheckable(True); btn.setFixedHeight(24)
            btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor)); btn.setStyleSheet(FSTYLE)
            btn.clicked.connect(lambda chk=False, k=key: self._set_filter(k))
            L.addWidget(btn); self.filter_btns[key] = btn
        self.filter_btns["all"].setChecked(True)

        L.addSpacing(10)
        self.btn_hover = QPushButton("👁️ Preview")
        self.btn_hover.setCheckable(True)
        self.btn_hover.setChecked(self.hover_enabled)
        self.btn_hover.setFixedHeight(24)
        self.btn_hover.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_hover.setStyleSheet(FSTYLE)
        self.btn_hover.clicked.connect(self._toggle_hover)
        L.addWidget(self.btn_hover)

        L.addStretch()
        self.lbl_count = QLabel("0 foto"); self.lbl_count.setObjectName("labelMuted")
        L.addWidget(self.lbl_count)
        return bar

    def _build_scroll(self):
        self.view = QListView()
        self.view.setObjectName("galleryGrid")
        self.view.setFrameShape(QFrame.Shape.NoFrame)
        self.view.setModel(self.model)
        self.view.setItemDelegate(self.delegate)
        self.view.setViewMode(QListView.ViewMode.IconMode)
        self.view.setResizeMode(QListView.ResizeMode.Adjust)
        self.view.setWrapping(True)
        self.view.setWordWrap(True)
        self.view.setSpacing(10)
        self.view.setUniformItemSizes(False) # Diperlukan agar sizeHint separator bekerja
        self.view.setMouseTracking(True) # Aktifkan pendeteksian mouse tanpa klik
        self.view.clicked.connect(self._on_view_clicked)
        self.view.entered.connect(self._on_view_entered)
        self.view.selectionModel().currentChanged.connect(self._on_current_changed)
        self.view.doubleClicked.connect(self._on_view_double_clicked)
        
        return self.view

    def _on_view_clicked(self, index: QModelIndex):
        if not index.isValid(): return
        path = index.data(GalleryModel.PathRole)
        item_type = index.data(GalleryModel.TypeRole)
        
        self._sel_path = path
        if item_type == 'p':
            self.photo_selected.emit(path)
        self.state_changed.emit()

    def _on_current_changed(self, current: QModelIndex, previous: QModelIndex):
        """Memperbarui pratinjau foto saat navigasi menggunakan keyboard."""
        if current.isValid():
            self._on_view_clicked(current)

    def _on_view_entered(self, index: QModelIndex):
        """Dipanggil saat mouse melewati (hover) sebuah item."""
        if not index.isValid() or not self.hover_enabled:
            return
            
        item_type = index.data(GalleryModel.TypeRole)
        if item_type == 'p':
            path = index.data(GalleryModel.PathRole)
            self.photo_selected.emit(path)

    def _on_view_double_clicked(self, index: QModelIndex):
        if not index.isValid(): return
        item_type = index.data(GalleryModel.TypeRole)
        path = index.data(GalleryModel.PathRole)
        
        if item_type in ('f', 'd'):
            self.load_folder(path)
        elif item_type == 'p':
            # Cari index foto di dalam self.filtered untuk lightbox
            idx = -1
            for i, p in enumerate(self.filtered):
                if p['path'] == path:
                    idx = i; break
            if idx != -1:
                self._card_click(self.filtered[idx], idx)

    # ── Load ──────────────────────────────────────
    def load_folder(self, folder: str, _push: bool = True):
        from ui.panel_left import DRIVES_MARKER, QUICK_ACCESS_MARKER

        # Guard: Hindari pemuatan ulang jika sudah berada di tampilan drive
        # Ini mencegah race condition saat restorasi startup (tiga kali panggil)
        if folder == DRIVES_MARKER and self._is_drives_view:
            return
        if folder == QUICK_ACCESS_MARKER and getattr(self, "_is_quick_access_view", False):
            return

        # Special case: show available drives as cards
        if folder == DRIVES_MARKER:
            if _push and self.current_folder:
                self._nav_history.append(self.current_folder)
            self.btn_back.setEnabled(bool(self._nav_history))
            self._sel_path = None
            self._show_drives_view()
            self.location_changed.emit(DRIVES_MARKER)
            return

        # Special case: Akses Cepat
        if folder == QUICK_ACCESS_MARKER:
            if _push and self.current_folder:
                self._nav_history.append(self.current_folder)
            self.btn_back.setEnabled(bool(self._nav_history))
            self._sel_path = None
            self._show_quick_access_view()
            self.location_changed.emit(QUICK_ACCESS_MARKER)
            return

        # Push current folder to history before navigating
        if _push and self.current_folder and self.current_folder != folder:
            self._nav_history.append(self.current_folder)
        self.btn_back.setEnabled(bool(self._nav_history))
        self._sel_path = None

        if self._scanner:
            self._scanner.cancel(); self._scanner = None
        self._progress_failsafe.stop()

        self.current_folder = folder
        self._is_drives_view = False   # ← leaving drives view
        self._is_quick_access_view = False

        self.photos = []; self._photo_paths_cache = set()

        # Subfolders for navigation
        self._subfolders = self._get_subfolders(folder)

        # DB photos (instant)
        db_photos = get_photos_in_folder(folder)
        if db_photos:
            self.photos = db_photos
            self._photo_paths_cache = {p['path'] for p in db_photos}

        self._apply_filter()
        self._start_scan(folder)
        self.location_changed.emit(folder)

    def _show_drives_view(self):
        """Show available drives. Respects current view_mode."""
        import string
        if self._scanner:
            self._scanner.cancel(); self._scanner = None
        self._progress_failsafe.stop()

        self._is_quick_access_view = False
        self._is_drives_view = True
        self.photos = []
        self.current_folder = None
        self._render_grid()

    def _show_quick_access_view(self):
        """Show quick access folders as cards."""
        if self._scanner:
            self._scanner.cancel(); self._scanner = None
        self._progress_failsafe.stop()

        self._is_drives_view = False
        self._is_quick_access_view = True
        self.photos = []
        self.current_folder = None
        self._render_grid()

    def _get_subfolders(self, folder: str) -> list[str]:
        try:
            return sorted(
                [e.path for e in os.scandir(folder)
                 if e.is_dir() and not e.name.startswith('.')],
                key=lambda p: os.path.basename(p).lower()
            )
        except (PermissionError, FileNotFoundError, OSError):
            return []

    def _open_folder(self):
        from PySide6.QtWidgets import QFileDialog
        path = QFileDialog.getExistingDirectory(self, "Pilih Folder Foto")
        if path: self.load_folder(path)

    def _nav_back(self):
        if not self._nav_history: return
        prev = self._nav_history.pop()
        self.load_folder(prev, _push=False)

    def _add_files(self):
        from PySide6.QtWidgets import QFileDialog
        from datetime import datetime
        paths, _ = QFileDialog.getOpenFileNames(self, "Pilih Foto",
            filter="Gambar (*.jpg *.jpeg *.png *.webp *.gif *.bmp *.tiff *.heic)")
        if not paths: return
        for path in paths:
            meta = {'path':path,'name':os.path.basename(path),
                    'folder':str(os.path.dirname(path)),
                    'file_size':os.path.getsize(path),
                    'added_at':datetime.now().isoformat(),'tags':{},'exif_data':{}}
            upsert_photo(meta)
            if path not in self._photo_paths_cache:
                self.photos.append(meta)
                self._photo_paths_cache.add(path)
        self._apply_filter()

    def _start_scan(self, folder: str):
        # Cancel any previous scanner
        if self._scanner:
            self._scanner.cancel()

        self._scan_token += 1
        token = self._scan_token
        self.prog_bar.setVisible(True); self.prog_lbl.setVisible(True)
        self.prog_bar.setValue(0); self.prog_lbl.setText("Memindai folder...")
        signals = ScannerSignals()
        signals.progress.connect(lambda done, total, t=token: self._on_scan_progress(t, done, total))
        signals.photo_found.connect(lambda meta, t=token: self._on_photo_found(t, meta))
        signals.finished.connect(lambda total, t=token: self._on_scan_done(t, total))
        # Keep strong Python ref so GC doesn't destroy QObject while thread runs
        self._scan_signals = signals
        self._scanner = FolderScanWorker(folder, signals)
        from PySide6.QtCore import QThreadPool
        QThreadPool.globalInstance().start(self._scanner)

        # Keep long scans visible until the worker explicitly finishes.
        self._progress_failsafe.stop()

    def _force_hide_progress(self):
        """Failsafe — hide progress bar if it's somehow still visible."""
        if self.prog_bar.isVisible():
            self.prog_bar.setVisible(False)
            self.prog_lbl.setVisible(False)

    def _on_scan_progress(self, token: int, done: int, total: int):
        if token != self._scan_token:
            return
        self.prog_bar.setValue(int(done/total*100) if total else 0)
        self.prog_lbl.setText(f"Memindai {done}/{total} foto...")

    def _on_photo_found(self, token: int, meta: dict):
        if token != self._scan_token:
            return
        
        path = meta['path']
        # Cepat: gunakan set() untuk cek duplikasi, bukan loop any()
        if path not in self._photo_paths_cache:
            self.photos.append(meta)
            self._photo_paths_cache.add(path)
            
            n = len(self.photos)
            # Progressive Rendering:
            # 10 foto pertama ditampilkan langsung satu per satu.
            # Setelah itu, UI hanya di-refresh setiap 25 foto baru untuk efisiensi.
            if n <= 10 or n % 25 == 0:
                self._apply_filter()

            # Jika item yang dicari ditemukan selama scan, paksa render dan gulir ke sana
            if self._pending_restore_selection == path:
                self._pending_restore_scroll = None
                self._apply_filter()
                self._restore_selection_state()
            else:
                self.lbl_count.setText(f"Memindai... {n} foto ditemukan")

    def _on_scan_done(self, token: int, total: int):
        if token != self._scan_token:
            return
        # Always hide progress regardless of total
        self._progress_failsafe.stop()
        self.prog_bar.setVisible(False)
        self.prog_lbl.setVisible(False)
        self.prog_bar.setValue(0)
        self._scan_signals = None   # release signals ref
        self._scanner      = None   # release worker ref
        self._apply_filter()
        self.btn_tag_all.setEnabled(bool(self.photos))
        self.btn_tag_new.setEnabled(bool(self.photos))
        self.stats_changed.emit(
            len(self.photos),
            sum(1 for p in self.photos if p.get('tagged'))
        )
        # Pastikan seleksi tetap dipulihkan jika belum terpilih selama scan
        self._restore_selection_state()
        self._restore_pending_scroll(finalize=True)

    def _toggle_hover(self, checked: bool):
        self.hover_enabled = checked
        self.state_changed.emit()

    # ── Filter / View ─────────────────────────────
    def _set_filter(self, key: str):
        for k,b in self.filter_btns.items(): b.setChecked(k==key)
        self.active_filter = key; self._apply_filter()
        self.state_changed.emit()

    def _set_view(self, mode: str):
        self.view_mode = mode
        self.delegate.view_mode = mode
        for m, btn in self._view_btns.items(): btn.setChecked(m==mode)
        self.view.doItemsLayout()
        self._render_grid()
        self.state_changed.emit()

    def _apply_filter(self):
        if self._is_drives_view or getattr(self, "_is_quick_access_view", False):
            return
            
        q = self.search.text().lower()
        f = self.active_filter
        si = self.sort_combo.currentIndex()

        # 1. Sort Subfolders (Gunakan Nama atau Tanggal Modifikasi)
        def fskey(fp):
            if si in (4, 5): # Tanggal Modifikasi
                try: return os.path.getmtime(fp)
                except: return 0
            return os.path.basename(fp).lower()
        self._subfolders.sort(key=fskey, reverse=si in (3, 4, 9))

        result = [p for p in self.photos if
            (not q or q in p.get('name','').lower()) and
            (f=="all" or (f=="untagged" and not p.get('tagged')) or
             (f=="tagged" and p.get('ai_tagged')) or (f=="fav" and p.get('fav')))]
        def skey(p):
            if si in (0,1): return p.get('added_at','')
            if si in (2,3): return p.get('name','').lower()
            if si in (4,5): return p.get('date_taken','') or ''
            if si in (8,9): 
                ext = os.path.splitext(p.get('name', ''))[1].lower()
                name = p.get('name', '').lower()
                return (ext, name)
            return p.get('file_size',0)
        result.sort(key=skey, reverse=si in (0,3,4,6,9))
        self.filtered = result
        parts = []
        if self._subfolders: parts.append(f"{len(self._subfolders)} folder")
        if result: parts.append(f"{len(result)} foto")
        self.lbl_count.setText("  ·  ".join(parts) if parts else "Kosong")
        self._render_grid()

    # ── Render ────────────────────────────────────
    def _render_grid(self):
        items = []
        if self._is_drives_view:
            import string
            drives = [f"{l}:\\" for l in string.ascii_uppercase if os.path.exists(f"{l}:\\")]
            si = self.sort_combo.currentIndex()
            drives.sort(key=lambda x: x.lower(), reverse=si in (3, 9))
            items.append(('s', "💾  Drive"))
            for d in drives: items.append(('d', d))
        elif getattr(self, "_is_quick_access_view", False):
            home = os.path.expanduser("~")
            folders = [os.path.join(home, f) for f in ["Pictures", "Desktop", "Downloads", "Documents", "Videos", "Music"]] + [home]
            valid = [f for f in folders if os.path.isdir(f)]
            items.append(('s', "⚡  Akses Cepat"))
            for f in valid: items.append(('f', f))
        else:
            if self._subfolders:
                items.append(('s', "📁  Subfolder"))
                for f in self._subfolders: items.append(('f', f))
            if self.filtered:
                if self._subfolders: items.append(('s', "🖼️  Foto"))
                for p in self.filtered:
                    items.append(('p', p))
                    self.thumb_loader.request(p['path'])
        
        if not items:
            items.append(('s', "📂  Folder Kosong"))
            
        self.model.set_items(items)
        self._restore_selection_state()
        self._restore_pending_scroll(finalize=True)

    def _sep(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color:#5a5a90;font-size:10px;font-weight:700;"
                          "padding:4px 0 2px 2px;")
        lbl.setFixedHeight(22); return lbl

    def _on_thumb_ready(self, path: str, thumb: str):
        pass

    def export_state(self) -> dict:
        current_location = "__drives__" if self._is_drives_view else self.current_folder
        nav_history = [
            path for path in self._nav_history
            if path == "__drives__" or os.path.isdir(path)
        ]

        selected_path = self._sel_path
        if selected_path and selected_path != "__drives__":
            if not (os.path.exists(selected_path) or os.path.isdir(selected_path)):
                selected_path = None

        return {
            "current_location": current_location,
            "nav_history": nav_history,
            "selected_path": selected_path,
            "view_mode": self.view_mode,
            "active_filter": self.active_filter,
            "hover_enabled": self.hover_enabled,
            "search_text": self.search.text(),
            "sort_index": self.sort_combo.currentIndex(),
            "scroll_x": self.view.horizontalScrollBar().value(),
            "scroll_y": self.view.verticalScrollBar().value(),
        }

    def restore_state(self, state: dict):
        if not isinstance(state, dict):
            return

        # 1. Pulihkan Lokasi Terlebih Dahulu (Penting untuk sinkronisasi view mode)
        current_location = state.get("current_location")
        if current_location == "__drives__":
            self.load_folder("__drives__", _push=False)
        elif current_location == "__quick_access__":
            self.load_folder("__quick_access__", _push=False)
        elif isinstance(current_location, str) and os.path.isdir(current_location):
            self.load_folder(current_location, _push=False)

        # 2. Pulihkan View Mode
        view_mode = state.get("view_mode")
        if view_mode in self._view_btns:
            self._set_view(view_mode)

        # 3. Pulihkan Filter dan Pencarian
        active_filter = state.get("active_filter")
        if active_filter in self.filter_btns:
            self._set_filter(active_filter)

        hover_enabled = state.get("hover_enabled", True)
        self.hover_enabled = hover_enabled
        if hasattr(self, 'btn_hover'):
            self.btn_hover.setChecked(hover_enabled)

        search_text = state.get("search_text")
        if isinstance(search_text, str):
            self.search.setText(search_text)

        sort_index = state.get("sort_index")
        if isinstance(sort_index, int) and 0 <= sort_index < self.sort_combo.count():
            self.sort_combo.setCurrentIndex(sort_index)

        # 4. Pulihkan Riwayat dan Seleksi
        self._nav_history = [
            path for path in state.get("nav_history", [])
            if path == "__drives__" or os.path.isdir(path)
        ]
        self.btn_back.setEnabled(bool(self._nav_history))

        selected_path = state.get("selected_path")
        self._pending_restore_selection = selected_path if isinstance(selected_path, str) else None
        scroll_x = state.get("scroll_x", 0)
        scroll_y = state.get("scroll_y", 0)
        if isinstance(scroll_x, int) and isinstance(scroll_y, int):
            self._pending_restore_scroll = (scroll_x, scroll_y)

        self._restore_selection_state()
        self._restore_pending_scroll(finalize=False)

    def _restore_selection_state(self):
        path = self._pending_restore_selection or self._sel_path
        if not path: return

        for i in range(self.model.rowCount()):
            idx = self.model.index(i)
            if idx.data(GalleryModel.PathRole) == path:
                self.view.setCurrentIndex(idx)
                if self._pending_restore_selection == path:
                    self.view.scrollTo(idx)
                    self._pending_restore_selection = None
                return True
        return False

    def _restore_pending_scroll(self, finalize: bool):
        if self._pending_restore_scroll is None:
            return
        sx, sy = self._pending_restore_scroll
        QTimer.singleShot(100, lambda: self.view.horizontalScrollBar().setValue(sx))
        QTimer.singleShot(100, lambda: self.view.verticalScrollBar().setValue(sy))
        if finalize:
            self._pending_restore_scroll = None

    def _select(self, path: str, widget=None):
        # Metode ini tidak lagi diperlukan secara manual karena ditangani oleh 
        # QListView selection model, namun tetap ada untuk kompatibilitas internal jika dipanggil.
        pass

    def keyPressEvent(self, e: QKeyEvent):
        key = e.key()
        if key == Qt.Key.Key_Left and e.modifiers() & Qt.KeyboardModifier.AltModifier:
            self._nav_back(); return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._activate_sel(); return
        super().keyPressEvent(e)

    def _activate_sel(self):
        idx = self.view.currentIndex()
        if idx.isValid():
            self._on_view_double_clicked(idx)

    def _card_click(self, photo: dict, index: int):
        lb = Lightbox(self.filtered, index, self)
        lb.exec()
        
        # Sinkronisasi posisi seleksi setelah Lightbox ditutup
        if 0 <= lb.current < len(self.filtered):
            target_photo = self.filtered[lb.current]
            path = target_photo['path']
            
            # Cari item di model untuk disinkronkan seleksinya
            for i in range(self.model.rowCount()):
                idx = self.model.index(i)
                if idx.data(GalleryModel.PathRole) == path:
                    self.view.setCurrentIndex(idx)
                    self.view.scrollTo(idx)
                    break

    def _on_fav(self, path: str):
        new = toggle_fav(path)
        for p in self.photos:
            if p['path']==path: p['fav']=new; break
        self._apply_filter()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._is_drives_view:
            QTimer.singleShot(80, self._show_drives_view)
        elif getattr(self, "_is_quick_access_view", False):
            QTimer.singleShot(80, self._show_quick_access_view)
        else:
            QTimer.singleShot(80, self._render_grid)


# ── Folder Card ───────────────────────────────────
class FolderCard(QFrame):
    clicked = Signal(); double_clicked = Signal()
    def __init__(self, folder_path: str, thumb_size: int = 160):
        super().__init__()
        self.setObjectName("card")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._selected = False
        L = QVBoxLayout(self); L.setContentsMargins(4,4,4,4); L.setSpacing(3)
        icon = QLabel("📁"); icon.setFixedSize(thumb_size, thumb_size)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setObjectName("thumbPlaceholder")
        icon.setStyleSheet(f"font-size:{thumb_size//3}px;")
        iw = QHBoxLayout(); iw.setContentsMargins(0,0,0,0)
        iw.addStretch(); iw.addWidget(icon); iw.addStretch()
        L.addLayout(iw)
        name = os.path.basename(folder_path)
        if len(name) > 22: name = name[:20]+"…"
        nl = QLabel(name); nl.setObjectName("labelMuted")
        nl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nl.setFixedHeight(15); nl.setStyleSheet("font-size:10px;"); L.addWidget(nl)
        try:
            n = len([e for e in os.scandir(folder_path) if not e.name.startswith('.')])
            cl = QLabel(f"{n} item"); cl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cl.setStyleSheet("color:#5a5a90;font-size:9px;"); cl.setFixedHeight(13)
            L.addWidget(cl)
        except PermissionError: pass
    def set_selected(self, sel: bool):
        self._selected = sel
        self.setProperty("selected", sel)
        self.style().unpolish(self)
        self.style().polish(self)
    def mousePressEvent(self, e):
        if e.button()==Qt.MouseButton.LeftButton: self.clicked.emit()
    def mouseDoubleClickEvent(self, e):
        if e.button()==Qt.MouseButton.LeftButton: self.double_clicked.emit()
    def enterEvent(self, e):
        pass
    def leaveEvent(self, e):
        pass


# ── Folder Row ────────────────────────────────────
class FolderRow(QFrame):
    clicked = Signal(); double_clicked = Signal()
    def __init__(self, folder_path: str):
        super().__init__()
        self._selected = False
        self.setObjectName("folderRow")
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor)); self.setFixedHeight(48)
        L = QHBoxLayout(self); L.setContentsMargins(8,4,8,4); L.setSpacing(10)
        icon = QLabel("📁"); icon.setFixedSize(36,36)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setObjectName("thumbPlaceholder")
        icon.setStyleSheet("font-size:18px;")
        L.addWidget(icon)
        nl = QLabel(os.path.basename(folder_path)); nl.setStyleSheet("font-size:12px;")
        L.addWidget(nl); L.addStretch()
        try:
            n = len([e for e in os.scandir(folder_path) if not e.name.startswith('.')])
            cl = QLabel(f"{n} item"); cl.setStyleSheet("color:#5a5a90;font-size:10px;min-width:50px;")
            L.addWidget(cl)
        except PermissionError: pass
    def set_selected(self, sel: bool):
        self._selected = sel
        self.setProperty("selected", sel)
        self.style().unpolish(self)
        self.style().polish(self)
    def mousePressEvent(self, e):
        if e.button()==Qt.MouseButton.LeftButton: self.clicked.emit()
    def mouseDoubleClickEvent(self, e):
        if e.button()==Qt.MouseButton.LeftButton: self.double_clicked.emit()


# ── Photo Card ────────────────────────────────────
class PhotoCard(QFrame):
    clicked = Signal(); double_clicked = Signal(); hovered = Signal(); fav_toggled = Signal(str)
    def __init__(self, photo: dict, thumb_size: int = 160):
        super().__init__()
        self.photo=photo; self.thumb_size=thumb_size
        self.setObjectName("card")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._selected = False
        L = QVBoxLayout(self); L.setContentsMargins(4,4,4,4); L.setSpacing(3)
        
        # Container Thumbnail
        self.thumb_label = QLabel(); self.thumb_label.setFixedSize(thumb_size,thumb_size)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setObjectName("thumbPlaceholder")
        tw = QHBoxLayout(); tw.setContentsMargins(0,0,0,0)
        tw.addStretch(); tw.addWidget(self.thumb_label); tw.addStretch()
        L.addLayout(tw)

        # Baris Info Atas (AI Badge + Fav)
        row = QHBoxLayout(); row.setContentsMargins(2,0,2,0); row.setSpacing(2)
        if photo.get('ai_tagged'):
            ai = QLabel("AI ✨"); ai.setStyleSheet(
                "background:rgba(167,139,250,.85);color:#fff;"
                "font-size:9px;font-weight:700;padding:1px 5px;border-radius:8px;")
            row.addWidget(ai)
        row.addStretch()
        fav = QToolButton(); fav.setText("⭐" if photo.get('fav') else "☆")
        fav.setFixedSize(22,22); fav.setStyleSheet(
            "QToolButton{background:transparent;border:none;font-size:12px;}"
            "QToolButton:hover{color:#fbbf24;}")
        fav.clicked.connect(lambda: self.fav_toggled.emit(photo['path']))
        row.addWidget(fav); L.addLayout(row)

        # Container Tags (Sinkron v4 visual)
        self.tag_container = QWidget()
        self.tag_layout = QHBoxLayout(self.tag_container)
        self.tag_layout.setContentsMargins(0,0,0,0); self.tag_layout.setSpacing(3)
        self.tag_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        L.addWidget(self.tag_container)
        # Re-enable visual tags (v4 standard)
        self._render_tags()

        name = photo.get('name','')
        if len(name)>22: name=name[:20]+"…"
        nl = QLabel(name); nl.setObjectName("labelMuted")
        nl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nl.setFixedHeight(15); nl.setStyleSheet("font-size:10px;"); L.addWidget(nl)

    def _render_tags(self):
        # Clear existing
        while self.tag_layout.count():
            item = self.tag_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
            
        tags = self.photo.get('tags', {})
        # Tampilkan maksimal 3 tag utama agar tidak berantakan di grid
        visible_keys = ['bg', 'konten', 'waktu', 'wilayah', 'mood']
        count = 0
        for k in visible_keys:
            val = tags.get(k)
            if val and count < 3:
                emoji = EMOJI_MAP.get(k, {}).get(val, '')
                color = TAG_COLORS.get(k, '#5a5a90')
                lbl = QLabel(f"{emoji} {val}" if emoji else val)
                lbl.setStyleSheet(f"background: {color}22; color: {color}; border-radius: 4px; font-size: 8px; font-weight: 700; padding: 1px 4px;")
                self.tag_layout.addWidget(lbl)
                count += 1
    def set_thumb(self, path: str):
        pix = QPixmap(path)
        if not pix.isNull():
            self.thumb_label.setPixmap(pix.scaled(
                self.thumb_size, self.thumb_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
    def set_selected(self, sel: bool):
        self._selected = sel
        self.setProperty("selected", sel)
        self.style().unpolish(self)
        self.style().polish(self)
    def mousePressEvent(self, e):
        if e.button()==Qt.MouseButton.LeftButton: self.clicked.emit()
    def mouseDoubleClickEvent(self, e):
        if e.button()==Qt.MouseButton.LeftButton: self.double_clicked.emit()
    def enterEvent(self, e):
        self.hovered.emit()
    def leaveEvent(self, e):
        pass


# ── List Row ──────────────────────────────────────
class ListRow(QFrame):
    clicked = Signal(); double_clicked = Signal(); hovered = Signal()
    def __init__(self, photo: dict):
        super().__init__()
        self._selected = False
        self.setObjectName("listRow")
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor)); self.setFixedHeight(56)
        L = QHBoxLayout(self); L.setContentsMargins(8,4,8,4); L.setSpacing(10)
        self.thumb = QLabel(); self.thumb.setFixedSize(46,46)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setObjectName("thumbPlaceholder"); L.addWidget(self.thumb)
        info = QVBoxLayout(); info.setSpacing(2)
        fav="⭐ " if photo.get('fav') else ""; ai="✨ " if photo.get('ai_tagged') else ""
        raw = photo.get('name','')
        if len(raw) > 55: raw = raw[:28]+"…"+raw[-24:]
        nl=QLabel(f"{fav}{ai}{raw}"); nl.setStyleSheet("font-size:12px;")
        info.addWidget(nl)
        tags=photo.get('tags',{})
        parts=[v for k,v in tags.items() if k in ('bg','konten','ruang','waktu') and v]
        tl=QLabel("  ·  ".join(parts) if parts else "Belum ditag")
        tl.setStyleSheet("color:#5a5a90;font-size:10px;"); info.addWidget(tl)
        L.addLayout(info); L.addStretch()
        sz=photo.get('file_size',0)
        sl=QLabel(f"{sz//1024}KB" if sz<1048576 else f"{sz//1048576}MB")
        sl.setStyleSheet("color:#5a5a90;font-size:10px;min-width:40px;"); L.addWidget(sl)
    def set_thumb(self, path: str):
        pix=QPixmap(path)
        if not pix.isNull():
            self.thumb.setPixmap(pix.scaled(46,46,Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
    def set_selected(self, sel: bool):
        self._selected = sel
        self.setProperty("selected", sel)
        self.style().unpolish(self)
        self.style().polish(self)
    def mousePressEvent(self, e):
        if e.button()==Qt.MouseButton.LeftButton: self.clicked.emit()
    def mouseDoubleClickEvent(self, e):
        if e.button()==Qt.MouseButton.LeftButton: self.double_clicked.emit()
    def enterEvent(self, e): self.hovered.emit()


# ── Lightbox Clickable Label ────────────────────────────────────────────────
class LightboxClickableLabel(QLabel):
    clicked_at = Signal(QPoint)
    dragged = Signal(QPoint)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.zoom_enabled = False
        self._last_pos = QPoint()
        self._press_pos = QPoint()
        self._is_drag_mode = False

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.pos()
            self._last_pos = event.pos()
            self._is_drag_mode = False
            if self.zoom_enabled:
                self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.zoom_enabled and (event.buttons() & Qt.MouseButton.LeftButton):
            # Jika pergerakan lebih dari 5 pixel, aktifkan mode drag
            if (event.pos() - self._press_pos).manhattanLength() > 5:
                self._is_drag_mode = True
            
            delta = event.pos() - self._last_pos
            self.dragged.emit(delta)
            self._last_pos = event.pos()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self.zoom_enabled:
                if not self._is_drag_mode:
                    self.clicked_at.emit(event.pos())
                else:
                    # Kembalikan ke tangan terbuka setelah selesai geser (drag)
                    self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
            else:
                self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        super().mouseReleaseEvent(event)


# ── Lightbox ──────────────────────────────────────
class Lightbox(QDialog):
    def __init__(self, photos: list[dict], index: int, parent=None, source="gallery"):
        super().__init__(parent)
        self.photos=photos; self.current=index; self.source=source
        self._zoom_level = 0  # 0: Fit, 1: 100%
        self._zoom_allowed = False
        
        # Pastikan dialog bisa menerima input keyboard dengan baik
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        
        self.setWindowFlags(Qt.WindowType.Dialog|Qt.WindowType.FramelessWindowHint)
        self.setModal(True); self.setStyleSheet("background-color:rgba(0,0,0,0.95);")
        self.setGeometry(QApplication.primaryScreen().geometry())
        self._build()

    def _build(self):
        L=QVBoxLayout(self); L.setContentsMargins(0,0,0,0); L.setSpacing(0)
        top=QWidget(); top.setFixedHeight(48); top.setStyleSheet("background:rgba(0,0,0,0.6);")
        TL=QHBoxLayout(top); TL.setContentsMargins(16,0,16,0)
        self.lbl_name=QLabel(""); self.lbl_name.setStyleSheet("color:#e0e0f0;font-size:13px;font-weight:600;")
        TL.addWidget(self.lbl_name); TL.addStretch()
        self.lbl_idx=QLabel(""); self.lbl_idx.setStyleSheet("color:#5a5a90;font-size:12px;")
        TL.addWidget(self.lbl_idx)
        
        # Sesuaikan tombol tutup berdasarkan sumber
        close_text = "✕ Kembali ke Peta" if self.source == "map" else "✕"
        self.btn_close = QPushButton(close_text)
        if self.source == "map":
            self.btn_close.setFixedWidth(140)
        else:
            self.btn_close.setFixedSize(32, 32)
            
        self.btn_close.setStyleSheet("QPushButton{background:rgba(255,255,255,.08);border:none;"
            "border-radius:16px;color:#fff;font-size:12px;}"
            "QPushButton:hover{background:rgba(255,255,255,.2);}")
        self.btn_close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_close.clicked.connect(self.close); TL.addWidget(self.btn_close); L.addWidget(top)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll.setStyleSheet("background:transparent;")
        self.scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.scroll.viewport().setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.img=LightboxClickableLabel()
        self.img.clicked_at.connect(self._on_click_zoom)
        self.img.dragged.connect(self._on_drag)
        self.img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img.setStyleSheet("background:transparent;")
        self.scroll.setWidget(self.img)
        L.addWidget(self.scroll)

        bot=QWidget(); bot.setFixedHeight(54); bot.setStyleSheet("background:rgba(0,0,0,0.6);")
        BL=QHBoxLayout(bot); BL.setContentsMargins(16,0,16,0); BL.setSpacing(8)
        BTN=("QPushButton{background:rgba(255,255,255,.08);border:none;"
             "border-radius:6px;color:#fff;padding:6px 16px;font-size:12px;}"
             "QPushButton:hover{background:rgba(255,255,255,.18);}")
        
        # SetFocusPolicy(NoFocus) agar tombol panah keyboard tidak 'terjebak' di tombol UI
        bp=QPushButton("◀  Sebelumnya"); bp.setStyleSheet(BTN); bp.clicked.connect(self._prev)
        bp.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        bn=QPushButton("Berikutnya  ▶"); bn.setStyleSheet(BTN); bn.clicked.connect(self._next)
        bn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        BL.addWidget(bp); BL.addWidget(bn); BL.addStretch()
        self.lbl_meta=QLabel(""); self.lbl_meta.setStyleSheet("color:#5a5a90;font-size:11px;")
        BL.addWidget(self.lbl_meta); L.addWidget(bot)
        self.setFocus()

    def _show(self):
        if not self.photos: return
        p=self.photos[self.current]
        self.lbl_name.setText(p.get('name',''))
        self.lbl_idx.setText(f"{self.current+1} / {len(self.photos)}")
        parts=[]
        if p.get('date_taken'): parts.append(p['date_taken'][:10])
        if p.get('camera'):     parts.append(p['camera'])
        if p.get('img_w'):      parts.append(f"{p['img_w']}×{p.get('img_h','')}")
        self.lbl_meta.setText("  ·  ".join(parts))
        pix=QPixmap(p['path'])
        if not pix.isNull():
            w=self.scroll.viewport().width(); h=self.scroll.viewport().height()
            
            # Zoom diaktifkan hanya jika resolusi gambar melebihi resolusi monitor
            self._zoom_allowed = pix.width() > w or pix.height() > h
            self.img.zoom_enabled = self._zoom_allowed

            if not self._zoom_allowed:
                self._zoom_level = 0
                self.img.setCursor(Qt.CursorShape.ArrowCursor)
                scaled = pix
            else:
                if self._zoom_level == 0:
                    self.img.setCursor(Qt.CursorShape.PointingHandCursor)
                    scaled = pix.scaled(w,h,Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation)
                else:
                    self.img.setCursor(Qt.CursorShape.OpenHandCursor)
                    scaled = pix
            
            self.img.setPixmap(scaled)
        else:
            self.img.setText("⚠️ Tidak bisa memuat gambar")

    def _on_click_zoom(self, pos: QPoint):
        if not self.img.pixmap(): return

        # Hitung koordinat relatif sebelum zoom berubah
        label_w, label_h = self.img.width(), self.img.height()
        pix_w, pix_h = self.img.pixmap().width(), self.img.pixmap().height()
        offset_x = (label_w - pix_w) // 2
        offset_y = (label_h - pix_h) // 2
        
        rel_x = (pos.x() - offset_x) / pix_w
        rel_y = (pos.y() - offset_y) / pix_h

        # Siklus: Fit -> 100% -> Fit
        self._zoom_level = (self._zoom_level + 1) % 2
        self._show()

        if self._zoom_level == 1:
            self.img.adjustSize()
            new_pix_w = self.img.pixmap().width()
            new_pix_h = self.img.pixmap().height()
            
            target_x = int(rel_x * new_pix_w)
            target_y = int(rel_y * new_pix_h)
            
            view_w = self.scroll.viewport().width()
            view_h = self.scroll.viewport().height()
            
            self.scroll.horizontalScrollBar().setValue(target_x - view_w // 2)
            self.scroll.verticalScrollBar().setValue(target_y - view_h // 2)

    def _on_drag(self, delta: QPoint):
        if self._zoom_level == 0: return
        h_bar = self.scroll.horizontalScrollBar()
        v_bar = self.scroll.verticalScrollBar()
        h_bar.setValue(h_bar.value() - delta.x())
        v_bar.setValue(v_bar.value() - delta.y())
        # Update last_pos di label agar drag terasa mulus
        self.img._last_pos = self.img.mapFromGlobal(QCursor.pos())

    def _prev(self):
        if self.current > 0:
            self.current -= 1
            self._zoom_level = 0  # Reset zoom saat ganti foto
            self._show()
    def _next(self):
        if self.current < len(self.photos) - 1:
            self.current += 1
            self._zoom_level = 0  # Reset zoom saat ganti foto
            self._show()

    def resizeEvent(self, e):
        if self.isVisible():
            self._show()  # Rescale gambar jika ukuran jendela berubah
        super().resizeEvent(e)

    def showEvent(self, e):
        """Dipanggil saat dialog muncul pertama kali di layar."""
        super().showEvent(e)
        # Panggil _show di sini agar viewport scroll area sudah memiliki ukuran yang benar
        QTimer.singleShot(0, self._show)

    def keyPressEvent(self, e: QKeyEvent):
        k=e.key()
        if k == Qt.Key.Key_Left:
            self._prev()
            e.accept()
        elif k == Qt.Key.Key_Right:
            self._next()
            e.accept()
        elif k in (Qt.Key.Key_Escape, Qt.Key.Key_Space):
            self.close()
            e.accept()
        else:
            super().keyPressEvent(e)


# ── Drive Card ───────────────────────────────────────────────────────────────
class DriveCard(QFrame):
    """Clickable card — list row, compact card, or grid card."""
    clicked = Signal(); double_clicked = Signal()

    def __init__(self, drive_path: str, list_mode: bool = False, compact: bool = False):
        super().__init__()
        self.setObjectName("card")
        self._selected = False
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        if list_mode:
            # List row: full width, short height
            self.setFixedHeight(42)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        elif compact:
            # Compact card: fixed small square like FolderCard compact
            self.setFixedSize(88, 88)
        else:
            # Grid card: fixed medium size
            self.setFixedSize(172, 80)

        is_small = list_mode or compact
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8 if is_small else 12,
                                  4 if is_small else 8,
                                  8 if is_small else 12,
                                  4 if is_small else 8)
        layout.setSpacing(6 if is_small else 10)

        icon = QLabel("💿")
        icon.setStyleSheet(f"font-size: {'14' if compact else ('18' if list_mode else '28')}px; background: transparent;")
        icon.setFixedSize(20 if compact else (24 if list_mode else 36),
                          20 if compact else (24 if list_mode else 36))
        if compact:
            icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)

        if not compact:
            info = QVBoxLayout()
            info.setSpacing(1)
            name_lbl = QLabel(drive_path)
            name_lbl.setStyleSheet(
                f"font-size: {'12' if list_mode else '14'}px; font-weight: 600;"
                " color: #e0e0f0; background: transparent;")
            info.addWidget(name_lbl)
            try:
                import shutil
                total, used, free = shutil.disk_usage(drive_path)
                gb = lambda b: f"{b/1024**3:.1f} GB"
                space_lbl = QLabel(f"{gb(free)} bebas / {gb(total)}")
                space_lbl.setStyleSheet(
                    "font-size: 10px; color: #5a5a90; background: transparent;")
                info.addWidget(space_lbl)
            except Exception:
                pass
            layout.addLayout(info)
            if list_mode:
                layout.addStretch()
        else:
            # Compact: just drive letter below icon
            layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            name_lbl = QLabel(drive_path[:2])  # e.g. "C:"
            name_lbl.setStyleSheet("font-size:9px;color:#e0e0f0;background:transparent;")
            name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(name_lbl)

    def set_selected(self, sel: bool):
        self._selected = sel
        self.setProperty("selected", sel)
        self.style().unpolish(self)
        self.style().polish(self)
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit()
    def enterEvent(self, event):
        pass
    def leaveEvent(self, event):
        pass
