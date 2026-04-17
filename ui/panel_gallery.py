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
    QButtonGroup
)
from PySide6.QtCore import Qt, Signal, QTimer, QPoint
from PySide6.QtGui import QPixmap, QCursor, QKeyEvent
import os

from core.thumbnailer import ThumbLoader, FolderScanWorker, ScannerSignals
from core.database import (
    init_db, upsert_photo, get_photos_in_folder,
    update_tags, toggle_fav, get_stats
)

init_db()


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
        self._cards: dict[str, 'PhotoCard'] = {}
        self._list_rows: dict[str, 'ListRow'] = {}
        self._folder_widgets: dict[str, object] = {}  # FolderCard/FolderRow/DriveCard
        self._all_items: list[tuple] = []
        self._item_pos: dict[str, tuple] = {}   # path → (row, col) visual grid position
        self._sel_path: str | None = None
        self._nav_history: list[str] = []
        self._is_drives_view: bool = False   # True when showing drive list
        self._scanner       = None
        self._scan_signals  = None
        self._scan_token    = 0
        self._view_btns: dict[str, QToolButton] = {}
        self._pending_restore_selection: str | None = None
        self._pending_restore_scroll: tuple[int, int] | None = None

        self.thumb_loader = ThumbLoader(self)
        self.thumb_loader.thumb_ready.connect(self._on_thumb_ready)
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
        w = QWidget(); w.setFixedHeight(20); w.setStyleSheet("background:#0d0d1a;")
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
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.grid_widget = QWidget(); self.grid_widget.setStyleSheet("background:#07070f;")
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setContentsMargins(12,12,12,12); self.grid_layout.setSpacing(8)
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.scroll.setWidget(self.grid_widget)
        # Simpan state saat scroll manual dilepas
        self.scroll.verticalScrollBar().sliderReleased.connect(self.state_changed)
        return self.scroll

    # ── Load ──────────────────────────────────────
    def load_folder(self, folder: str, _push: bool = True):
        from ui.panel_left import DRIVES_MARKER

        # Special case: show available drives as cards
        if folder == DRIVES_MARKER:
            if _push and self.current_folder:
                self._nav_history.append(self.current_folder)
            self.btn_back.setEnabled(bool(self._nav_history))
            self._sel_path = None
            self._show_drives_view()
            self.location_changed.emit(DRIVES_MARKER)
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

        # Always reset so old photos never bleed into new folder
        self.photos = []; self._cards.clear(); self._photo_paths_cache = set()

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

        self.photos = []; self._cards.clear()
        self.current_folder = None
        self._is_drives_view = True

        # Clear grid
        self._folder_widgets.clear()
        self._all_items.clear()
        self._item_pos.clear()
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        drives = [
            f"{l}:\\" for l in string.ascii_uppercase
            if os.path.exists(f"{l}:\\")
        ]

        self.prog_bar.setVisible(False)
        self.prog_lbl.setVisible(False)
        self.lbl_count.setText(f"{len(drives)} drive")

        for d in drives:
            self._all_items.append(('f', d))

        if self.view_mode == 'list':
            # Show drives as rows
            self.grid_layout.addWidget(self._sep("💾  Drive"), 0, 0)
            for i, drive in enumerate(drives):
                card = DriveCard(drive, list_mode=True)
                self._folder_widgets[drive] = card
                self._item_pos[drive] = (i + 1, 0)
                card.clicked.connect(lambda d=drive, w=card: self._select(d, w))
                card.double_clicked.connect(lambda d=drive: self.load_folder(d))
                self.grid_layout.addWidget(card, i + 1, 0)
        else:
            # Grid / compact — card minimum width matches FolderCard
            min_w = 80 if self.view_mode == 'compact' else 150
            vw = self.scroll.viewport().width() or 800
            cols = max(1, (vw - 36) // (min_w + 8))
            for i, drive in enumerate(drives):
                card = DriveCard(drive, compact=(self.view_mode == "compact"))
                self._folder_widgets[drive] = card
                r, c2 = divmod(i, cols)
                self._item_pos[drive] = (r, c2)
                card.clicked.connect(lambda d=drive, w=card: self._select(d, w))
                card.double_clicked.connect(lambda d=drive: self.load_folder(d))
                self.grid_layout.addWidget(card, r, c2)
            for col in range(cols):
                self.grid_layout.setColumnStretch(col, 1)
                self.grid_layout.setColumnMinimumWidth(col, min_w)
        self._restore_selection_state()
        self._restore_pending_scroll(finalize=True)

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
        for m, btn in self._view_btns.items(): btn.setChecked(m==mode)
        # If currently showing drives, re-render drives (not folder grid)
        if self._is_drives_view:
            self._show_drives_view()
        else:
            self._render_grid()
        self.state_changed.emit()

    def _apply_filter(self):
        q = self.search.text().lower()
        f = self.active_filter
        si = self.sort_combo.currentIndex()
        result = [p for p in self.photos if
            (not q or q in p.get('name','').lower()) and
            (f=="all" or (f=="untagged" and not p.get('tagged')) or
             (f=="tagged" and p.get('ai_tagged')) or (f=="fav" and p.get('fav')))]
        def skey(p):
            if si in (0,1): return p.get('added_at','')
            if si in (2,3): return p.get('name','').lower()
            if si in (4,5): return p.get('date_taken','') or ''
            return p.get('file_size',0)
        result.sort(key=skey, reverse=si in (0,3,4,6))
        self.filtered = result
        parts = []
        if self._subfolders: parts.append(f"{len(self._subfolders)} folder")
        if result: parts.append(f"{len(result)} foto")
        self.lbl_count.setText("  ·  ".join(parts) if parts else "Kosong")
        self._render_grid()

    # ── Render ────────────────────────────────────
    def _render_grid(self):
        self._cards.clear()
        self._list_rows.clear()
        self._folder_widgets.clear()
        self._all_items.clear()
        self._item_pos.clear()
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        has_f = bool(self._subfolders)
        has_p = bool(self.filtered)

        if not has_f and not has_p:
            lbl = QLabel("📂  Belum ada foto\n\nBuka folder atau tambah foto untuk memulai")
            lbl.setObjectName("labelMuted"); lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.grid_layout.addWidget(lbl, 0, 0); return

        # Build flat list for keyboard navigation
        for fp in self._subfolders: self._all_items.append(('f', fp))
        for ph in self.filtered:    self._all_items.append(('p', ph))

        # ── List mode ──────────────────────────────
        if self.view_mode == "list":
            row = 0
            if has_f:
                self.grid_layout.addWidget(self._sep("📁  Subfolder"), row, 0); row+=1
                for fp in self._subfolders:
                    w = FolderRow(fp)
                    self._folder_widgets[fp] = w
                    self._item_pos[fp] = (row, 0)
                    w.clicked.connect(lambda p=fp, ww=w: self._select(p, ww))
                    w.double_clicked.connect(lambda p=fp: self.load_folder(p))
                    self.grid_layout.addWidget(w, row, 0); row+=1
            if has_p:
                if has_f:
                    self.grid_layout.addWidget(self._sep("🖼️  Foto"), row, 0); row+=1
                for i, photo in enumerate(self.filtered):
                    w = ListRow(photo)
                    self._item_pos[photo['path']] = (row, 0)
                    w.clicked.connect(lambda p=photo, ww=w: self._select(p['path'], ww))
                    w.double_clicked.connect(lambda p=photo, idx=i: self._card_click(p, idx))
                    w.hovered.connect(lambda p=photo: self.photo_selected.emit(p['path']) if self.hover_enabled else None)
                    self._list_rows[photo['path']] = w
                    self.grid_layout.addWidget(w, row, 0)
                    self.thumb_loader.request(photo['path']); row+=1
            return

        # ── Grid / Compact ──────────────────────────
        ts = 80 if self.view_mode == "compact" else 160
        card_w = self.COMPACT_CARD_WIDTH if self.view_mode == "compact" else self.GRID_CARD_WIDTH
        vw = self.scroll.viewport().width() or 800
        cols = max(1, (vw - 36) // (card_w + 8))

        items = [('f',fp) for fp in self._subfolders] + [('p',ph) for ph in self.filtered]
        need_photo_sep = has_f and has_p
        sep_inserted = False
        gi = 0

        for item_type, item_data in items:
            if need_photo_sep and item_type=='p' and not sep_inserted:
                sep_inserted = True
                if gi % cols != 0:
                    gi = ((gi // cols) + 1) * cols
                sr = gi // cols
                self.grid_layout.addWidget(self._sep("🖼️  Foto"), sr, 0, 1, cols)
                gi = (sr+1) * cols

            r, c = divmod(gi, cols)
            if item_type == 'f':
                card = FolderCard(item_data, ts)
                card.setFixedWidth(card_w)
                self._folder_widgets[item_data] = card
                self._item_pos[item_data] = (r, c)
                card.clicked.connect(lambda p=item_data, w=card: self._select(p, w))
                card.double_clicked.connect(lambda p=item_data: self.load_folder(p))
                self.grid_layout.addWidget(card, r, c)
            else:
                photo = item_data
                pidx = self.filtered.index(photo)
                card = PhotoCard(photo, ts)
                card.setFixedWidth(card_w)
                self._item_pos[photo['path']] = (r, c)
                card.clicked.connect(lambda p=photo, w=card: self._select(p['path'], w))
                card.double_clicked.connect(lambda p=photo, i=pidx: self._card_click(p, i))
                card.hovered.connect(lambda p=photo: self.photo_selected.emit(p['path']) if self.hover_enabled else None)
                card.fav_toggled.connect(self._on_fav)
                self._cards[photo['path']] = card
                self.grid_layout.addWidget(card, r, c)
                self.thumb_loader.request(photo['path'])
            gi += 1

        if True:
            # Compact: fixed-size cards, align left — no stretch
            self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            for col in range(cols):
                self.grid_layout.setColumnStretch(col, 0)
                self.grid_layout.setColumnMinimumWidth(col, card_w)
        else:
            # Grid: cards expand equally to fill width
            self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
            for col in range(cols):
                self.grid_layout.setColumnStretch(col, 0)
                self.grid_layout.setColumnMinimumWidth(col, card_w)
        self._restore_selection_state()
        self._restore_pending_scroll(finalize=False)

    def _sep(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("color:#5a5a90;font-size:10px;font-weight:700;"
                          "padding:4px 0 2px 2px;")
        lbl.setFixedHeight(22); return lbl

    def _on_thumb_ready(self, path: str, thumb: str):
        card = self._cards.get(path)
        if card: card.set_thumb(thumb)
        row = self._list_rows.get(path)
        if row: row.set_thumb(thumb)

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
            "scroll_x": self.scroll.horizontalScrollBar().value(),
            "scroll_y": self.scroll.verticalScrollBar().value(),
        }

    def restore_state(self, state: dict):
        if not isinstance(state, dict):
            return

        view_mode = state.get("view_mode")
        if view_mode in self._view_btns:
            self.view_mode = view_mode
            for mode, btn in self._view_btns.items():
                btn.setChecked(mode == view_mode)

        active_filter = state.get("active_filter")
        if active_filter in self.filter_btns:
            self.active_filter = active_filter
            for key, btn in self.filter_btns.items():
                btn.setChecked(key == active_filter)

        hover_enabled = state.get("hover_enabled", True)
        self.hover_enabled = hover_enabled
        if hasattr(self, 'btn_hover'):
            self.btn_hover.setChecked(hover_enabled)

        sort_index = state.get("sort_index")
        if isinstance(sort_index, int) and 0 <= sort_index < self.sort_combo.count():
            self.sort_combo.setCurrentIndex(sort_index)

        search_text = state.get("search_text")
        if isinstance(search_text, str):
            self.search.setText(search_text)

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

        current_location = state.get("current_location")
        if current_location == "__drives__":
            self.load_folder("__drives__", _push=False)
        elif isinstance(current_location, str) and os.path.isdir(current_location):
            self.load_folder(current_location, _push=False)
        else:
            self._restore_selection_state()
            self._restore_pending_scroll(finalize=False)

    def _restore_selection_state(self):
        # Prioritaskan path yang sedang direstorasi, jika tidak ada gunakan yang terakhir dipilih
        path = self._pending_restore_selection or self._sel_path
        if not path:
            return

        widget = (self._cards.get(path) or self._list_rows.get(path)
                  or self._folder_widgets.get(path))

        if widget:
            # Sorot widget secara visual (widget=None agar tidak double scroll)
            self._select(path, widget=None)

            # Jika sedang memulihkan seleksi (setelah startup atau pindah folder)
            if self._pending_restore_selection == path:
                self._pending_restore_scroll = None
                
                # Memaksa kontainer untuk sinkronisasi geometri. Tanpa ini, 
                # ensureWidgetVisible sering gagal karena tinggi widget dianggap 0.
                self.grid_widget.adjustSize()

                # NOTE: Revisit later. In very large folders, ensureWidgetVisible 
                # sometimes fails to align correctly due to layout race conditions.
                def perform_scroll():
                    try:
                        # Check if widget still exists and is visible
                        if not widget.isHidden():
                            self.scroll.ensureWidgetVisible(widget, 50, 150)
                    except RuntimeError:
                        # Occurs if widget was deleted (e.g. folder changed) before timer fired
                        pass
                
                QTimer.singleShot(500, perform_scroll)
                self._pending_restore_selection = None
            return True
        return False

    def _restore_pending_scroll(self, finalize: bool):
        if self._pending_restore_scroll is None:
            return
        sx, sy = self._pending_restore_scroll

        def apply():
            self.scroll.horizontalScrollBar().setValue(sx)
            self.scroll.verticalScrollBar().setValue(sy)

        QTimer.singleShot(100, apply)
        if finalize:
            self._pending_restore_scroll = None

    def _select(self, path: str, widget=None):
        """Single click: highlight + preview. Hover does NOT clear selection."""
        self._sel_path = path
        # Update photo cards
        for p, card in self._cards.items(): card.set_selected(p == path)
        # Update list rows
        for p, row in self._list_rows.items(): row.set_selected(p == path)
        # Update folder widgets (FolderCard, FolderRow, DriveCard)
        for p, fw in self._folder_widgets.items(): fw.set_selected(p == path)
        # Emit preview only for image files
        if os.path.isfile(path):
            self.photo_selected.emit(path)
        # Scroll grid_widget so selected item is visible
        if widget:
            QTimer.singleShot(0, lambda: self.scroll.ensureWidgetVisible(widget, 20, 20))
        self.setFocus()

    def keyPressEvent(self, e: QKeyEvent):
        key = e.key()
        if key == Qt.Key.Key_Left and e.modifiers() & Qt.KeyboardModifier.AltModifier:
            self._nav_back(); return
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down):
            self._move_sel(key); return
        if key == Qt.Key.Key_Home:
            self._jump_to_index(0); return
        if key == Qt.Key.Key_End:
            self._jump_to_index(len(self._all_items) - 1); return
        if key in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown):
            self._page_move(key); return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._activate_sel(); return
        super().keyPressEvent(e)

    def _move_sel(self, key):
        if not self._all_items: return
        cur = next((i for i,(t,d) in enumerate(self._all_items)
                    if (d if t=='f' else d['path']) == self._sel_path), -1)
        n = len(self._all_items)

        if self.view_mode == 'list':
            # List: simple up/down, no wrapping
            step = -1 if key == Qt.Key.Key_Up else 1
            nxt = max(0, min(n - 1, max(cur, 0) + step))
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            # Left/Right: step ±1 with wrapping across rows (original behaviour)
            step = -1 if key == Qt.Key.Key_Left else 1
            nxt = max(0, min(n - 1, max(cur, 0) + step))
        else:
            # Up/Down: use visual (row, col) positions to navigate correctly
            # even across the folder/photo separator gap
            cur_path = self._sel_path
            cur_pos  = self._item_pos.get(cur_path, (0, 0))
            cur_row, cur_col = cur_pos
            target_row = cur_row - 1 if key == Qt.Key.Key_Up else cur_row + 1

            # Find item whose visual row is closest to target_row
            # and whose col is closest to cur_col
            best_idx  = -1
            best_dist = None
            for i, (t, d) in enumerate(self._all_items):
                p = d if t == 'f' else d['path']
                pos = self._item_pos.get(p)
                if pos is None: continue
                r, c = pos
                if key == Qt.Key.Key_Up:
                    if r >= cur_row: continue   # must be above
                elif key == Qt.Key.Key_Down:
                    if r <= cur_row: continue   # must be below

                row_dist = abs(r - target_row)
                col_dist = abs(c - cur_col)
                dist = row_dist * 100 + col_dist   # row distance dominates
                if best_dist is None or dist < best_dist:
                    best_dist = dist
                    best_idx  = i

            nxt = best_idx if best_idx >= 0 else cur

        nxt = max(0, min(n - 1, nxt))
        t, d = self._all_items[nxt]
        path = d if t == 'f' else d['path']
        w = (self._cards.get(path) or self._list_rows.get(path)
             or self._folder_widgets.get(path))
        self._select(path, w)

    def _jump_to_index(self, idx: int):
        if not self._all_items or idx < 0 or idx >= len(self._all_items): return
        t, d = self._all_items[idx]
        path = d if t == 'f' else d['path']
        w = (self._cards.get(path) or self._list_rows.get(path)
             or self._folder_widgets.get(path))
        self._select(path, w)

    def _page_move(self, key):
        if not self._all_items:
            return

        cur = next((i for i, (t, d) in enumerate(self._all_items)
                    if (d if t == 'f' else d['path']) == self._sel_path), 0)
        direction = -1 if key == Qt.Key.Key_PageUp else 1

        if self.view_mode == 'list':
            row_h = 56
            visible_rows = max(1, self.scroll.viewport().height() // row_h)
            step = visible_rows
        else:
            card_w = self.COMPACT_CARD_WIDTH if self.view_mode == "compact" else self.GRID_CARD_WIDTH
            cols = max(1, (self.scroll.viewport().width() - 36) // (card_w + 8))
            row_h = 120 if self.view_mode == "compact" else 210
            visible_rows = max(1, self.scroll.viewport().height() // row_h)
            step = max(1, visible_rows * cols)

        nxt = max(0, min(len(self._all_items) - 1, cur + direction * step))
        t, d = self._all_items[nxt]
        path = d if t == 'f' else d['path']
        w = (self._cards.get(path) or self._list_rows.get(path)
             or self._folder_widgets.get(path))
        self._select(path, w)

    def _activate_sel(self):
        if not self._sel_path: return
        for t, d in self._all_items:
            p = d if t=='f' else d['path']
            if p == self._sel_path:
                if t == 'f': self.load_folder(p)
                else:
                    idx = next((i for i,ph in enumerate(self.filtered) if ph['path']==p), 0)
                    self._card_click(d, idx)
                break

    def _card_click(self, photo: dict, index: int):
        lb = Lightbox(self.filtered, index, self)
        lb.exec()
        
        # Sinkronisasi posisi seleksi setelah Lightbox ditutup
        if 0 <= lb.current < len(self.filtered):
            target_photo = self.filtered[lb.current]
            path = target_photo['path']
            widget = self._cards.get(path) or self._list_rows.get(path)
            self._select(path, widget)

    def _on_fav(self, path: str):
        new = toggle_fav(path)
        for p in self.photos:
            if p['path']==path: p['fav']=new; break
        self._apply_filter()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._is_drives_view:
            QTimer.singleShot(80, self._show_drives_view)
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
        icon.setStyleSheet(f"background:#141425;border-radius:6px;font-size:{thumb_size//3}px;")
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
        self.setStyleSheet("QFrame#card{background:#1a1a20;border:2px solid #fbbf24;border-radius:10px;}" if sel else "")
    def mousePressEvent(self, e):
        if e.button()==Qt.MouseButton.LeftButton: self.clicked.emit()
    def mouseDoubleClickEvent(self, e):
        if e.button()==Qt.MouseButton.LeftButton: self.double_clicked.emit()
    def enterEvent(self, e):
        if not self._selected:
            self.setStyleSheet("QFrame#card{background:#10101e;border:1px solid #fbbf24;border-radius:10px;}")
    def leaveEvent(self, e):
        if not self._selected: self.setStyleSheet("")


# ── Folder Row ────────────────────────────────────
class FolderRow(QFrame):
    clicked = Signal(); double_clicked = Signal()
    def __init__(self, folder_path: str):
        super().__init__()
        self._selected = False
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor)); self.setFixedHeight(48)
        self._base = "QFrame{border-bottom:1px solid #141425;}QFrame:hover{background:#10101e;}"
        self.setStyleSheet(self._base)
        L = QHBoxLayout(self); L.setContentsMargins(8,4,8,4); L.setSpacing(10)
        icon = QLabel("📁"); icon.setFixedSize(36,36)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("background:#141425;border-radius:4px;font-size:18px;")
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
        self.setStyleSheet("QFrame{border-bottom:1px solid #141425;background:#1a1a35;border-left:3px solid #fbbf24;}" if sel else self._base)
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
        self.thumb_label = QLabel(); self.thumb_label.setFixedSize(thumb_size,thumb_size)
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setStyleSheet("background:#141425;border-radius:6px;")
        tw = QHBoxLayout(); tw.setContentsMargins(0,0,0,0)
        tw.addStretch(); tw.addWidget(self.thumb_label); tw.addStretch()
        L.addLayout(tw)
        row = QHBoxLayout(); row.setContentsMargins(0,0,0,0); row.setSpacing(2)
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
        name = photo.get('name','')
        if len(name)>22: name=name[:20]+"…"
        nl = QLabel(name); nl.setObjectName("labelMuted")
        nl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        nl.setFixedHeight(15); nl.setStyleSheet("font-size:10px;"); L.addWidget(nl)
    def set_thumb(self, path: str):
        pix = QPixmap(path)
        if not pix.isNull():
            self.thumb_label.setPixmap(pix.scaled(
                self.thumb_size, self.thumb_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
    def set_selected(self, sel: bool):
        self._selected = sel
        self.setStyleSheet("QFrame#card{background:#1a1a35;border:2px solid #a78bfa;border-radius:10px;}" if sel else "")
    def mousePressEvent(self, e):
        if e.button()==Qt.MouseButton.LeftButton: self.clicked.emit()
    def mouseDoubleClickEvent(self, e):
        if e.button()==Qt.MouseButton.LeftButton: self.double_clicked.emit()
    def enterEvent(self, e):
        self.hovered.emit()
        if not self._selected:
            self.setStyleSheet("QFrame#card{background:#10101e;border:1px solid #60a5fa;border-radius:10px;}")
    def leaveEvent(self, e):
        if not self._selected: self.setStyleSheet("")


# ── List Row ──────────────────────────────────────
class ListRow(QFrame):
    clicked = Signal(); double_clicked = Signal(); hovered = Signal()
    def __init__(self, photo: dict):
        super().__init__()
        self._selected = False
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor)); self.setFixedHeight(56)
        self._base = "QFrame{border-bottom:1px solid #141425;}QFrame:hover{background:#10101e;}"
        self.setStyleSheet(self._base)
        L = QHBoxLayout(self); L.setContentsMargins(8,4,8,4); L.setSpacing(10)
        self.thumb = QLabel(); self.thumb.setFixedSize(46,46)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setStyleSheet("background:#141425;border-radius:4px;"); L.addWidget(self.thumb)
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
        self.setStyleSheet("QFrame{border-bottom:1px solid #141425;background:#1a1a35;border-left:3px solid #a78bfa;}" if sel else self._base)
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
        self._last_pos = QPoint()
        self._press_pos = QPoint()
        self._is_drag_mode = False

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.pos()
            self._last_pos = event.pos()
            self._is_drag_mode = False
            self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            # Jika pergerakan lebih dari 5 pixel, aktifkan mode drag
            if (event.pos() - self._press_pos).manhattanLength() > 5:
                self._is_drag_mode = True
            
            delta = event.pos() - self._last_pos
            self.dragged.emit(delta)
            # Update last_pos secara manual untuk kelancaran drag di scroll area
            self._last_pos = self.mapFromGlobal(QCursor.pos())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            if not self._is_drag_mode:
                self.clicked_at.emit(event.pos())
        super().mouseReleaseEvent(event)


# ── Lightbox ──────────────────────────────────────
class Lightbox(QDialog):
    def __init__(self, photos: list[dict], index: int, parent=None):
        super().__init__(parent)
        self.photos=photos; self.current=index
        self._zoom_level = 0  # 0: Fit, 1: 100%
        
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
        close=QPushButton("✕"); close.setFixedSize(32,32)
        close.setStyleSheet("QPushButton{background:rgba(255,255,255,.08);border:none;"
            "border-radius:16px;color:#fff;font-size:14px;}"
            "QPushButton:hover{background:rgba(255,255,255,.2);}")
        close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close.clicked.connect(self.close); TL.addWidget(close); L.addWidget(top)

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
            if self._zoom_level == 1:
                # Mode 100%
                scaled = pix
            else:
                # Mode Fit
                w=self.scroll.viewport().width(); h=self.scroll.viewport().height()
                scaled = pix.scaled(w,h,Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation)
            
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
        self.setStyleSheet(
            "QFrame#card{background:#1a1a35;border:2px solid #60a5fa;border-radius:10px;}"
            if sel else "")
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit()
    def enterEvent(self, event):
        if not getattr(self, "_selected", False):
            self.setStyleSheet(
                "QFrame#card{background:#10101e;border:1px solid #60a5fa;"
                "border-radius:10px;}")
    def leaveEvent(self, event):
        if not getattr(self, "_selected", False):
            self.setStyleSheet("")
