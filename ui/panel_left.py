"""
ui/panel_left.py

Fixes:
  - Arrow always visible (not just on hover) via QProxyStyle custom drawing
  - "Drive" header clickable — emits DRIVES_MARKER so gallery shows drive list
  - setExpandsOnDoubleClick(False) — expand only via arrow, not double-click
"""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QSplitter, QTreeWidget,
    QTreeWidgetItem, QLabel, QPushButton,
    QHBoxLayout, QSizePolicy, QStyle, QProxyStyle,
    QScrollArea, QFrame
)
from PySide6.QtCore import Qt, Signal, QPointF, QPoint
from PySide6.QtGui import QPixmap, QPainter, QColor, QPolygonF, QCursor, QPen
import os

# Special marker emitted when user clicks the "💾 Drive" header
DRIVES_MARKER = "__drives__"
QUICK_ACCESS_MARKER = "__quick_access__"


# ── Custom proxy style: always-visible tree arrows ───────────────────────────
class TreeArrowStyle(QProxyStyle):
    """
    Draws tree branch arrows in a visible color so they are always
    shown against the dark background — not just on hover.
    """
    def drawPrimitive(self, element, option, painter, widget=None):
        if element == QStyle.PrimitiveElement.PE_IndicatorBranch:
            # Only draw arrow if this item HAS children
            if not (option.state & QStyle.StateFlag.State_Children):
                return   # leaf node — draw nothing

            r    = option.rect
            
            # Gunakan seluruh dimensi rect untuk menentukan titik tengah yang akurat
            cx   = r.x() + r.width()  / 2.0
            cy   = r.y() + r.height() / 2.0
            half = min(r.width(), r.height()) * 0.30

            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            
            # Deteksi seleksi yang lebih kuat: Ambil item di koordinat Y yang sama (tengah baris)
            is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
            if not is_selected and widget:
                # Cek item di tengah viewport pada ketinggian yang sama dengan branch ini
                target_item = widget.itemAt(QPoint(widget.viewport().width() // 2, cy))
                if target_item:
                    is_selected = target_item.isSelected()

            is_hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
            accent_color = widget.palette().highlight().color()
            text_color = widget.palette().windowText().color()

            if is_selected:
                # Background baris adalah warna aksen, paksa Putih agar kontras
                painter.setBrush(QColor("#ffffff"))
            elif is_hover:
                painter.setBrush(accent_color)
            else:
                painter.setBrush(text_color)
                painter.setOpacity(0.7)

            painter.setPen(Qt.PenStyle.NoPen)

            if option.state & QStyle.StateFlag.State_Open:
                # Expanded ▼
                poly = QPolygonF([QPointF(cx - half, cy - half * 0.5), QPointF(cx + half, cy - half * 0.5), QPointF(cx, cy + half)])
            else:
                # Collapsed ▶
                poly = QPolygonF([QPointF(cx - half * 0.5, cy - half), QPointF(cx + half, cy), QPointF(cx - half * 0.5, cy + half)])

            painter.drawPolygon(poly)
            painter.restore()
            return   # skip default drawing

        super().drawPrimitive(element, option, painter, widget)


# ── Left panel container ─────────────────────────────────────────────────────
class LeftPanel(QWidget):
    folder_selected = Signal(str)  # real path OR DRIVES_MARKER

    def __init__(self):
        super().__init__()
        self.setMinimumWidth(180)
        self.setMaximumWidth(400)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.v_splitter = QSplitter(Qt.Orientation.Vertical)
        self.v_splitter.setHandleWidth(1)
        self.v_splitter.setChildrenCollapsible(False)
        layout.addWidget(self.v_splitter)

        self.tree_widget = FolderTreeWidget()
        self.tree_widget.folder_selected.connect(self.folder_selected)
        self.v_splitter.addWidget(self.tree_widget)

        self.preview_widget = PreviewWidget()
        self.v_splitter.addWidget(self.preview_widget)

        self.v_splitter.setSizes([400, 260])

    def show_preview(self, path: str):
        # Reset ke mode "Fit" setiap kali gambar baru dipilih
        self.preview_widget._zoom_level = 0
        self.preview_widget.load(path)

    def populate_tree(self, root_path: str):
        self.tree_widget.populate(root_path)

    def export_tree_state(self) -> dict:
        return self.tree_widget.export_state()

    def restore_tree_state(self, state: dict):
        self.tree_widget.restore_state(state)

    def sync_to_path(self, path: str):
        self.tree_widget.select_path(path)


# ── Folder Tree ──────────────────────────────────────────────────────────────
class FolderTreeWidget(QWidget):
    folder_selected = Signal(str)  # real path OR DRIVES_MARKER

    def __init__(self):
        super().__init__()
        self._custom_root_path: str | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header bar
        header = QWidget()
        header.setObjectName("toolbar")
        header.setFixedHeight(34)
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(8, 0, 8, 0)
        lbl = QLabel("📁  Folder")
        lbl.setObjectName("labelMuted")
        h_layout.addWidget(lbl)
        h_layout.addStretch()
        btn_open = QPushButton("＋")
        btn_open.setObjectName("navBtn")
        btn_open.setFixedSize(22, 22)
        btn_open.setToolTip("Buka Folder")
        btn_open.clicked.connect(self._open_folder)
        h_layout.addWidget(btn_open)
        layout.addWidget(header)

        # Tree widget
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(16)
        self.tree.setAnimated(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setExpandsOnDoubleClick(False)   # arrow-click only

        # Custom style → arrows always visible on dark background
        self.tree.setStyle(TreeArrowStyle(self.tree.style()))

        layout.addWidget(self.tree)

        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.itemExpanded.connect(self._on_item_expanded)

        self._populate_defaults()

    # ── Helpers ──────────────────────────────────────
    def _has_subfolders(self, path: str) -> bool:
        try:
            for e in os.scandir(path):
                if e.is_dir() and not e.name.startswith('.'):
                    return True
        except (PermissionError, OSError):
            pass
        return False

    def _get_drives(self) -> list[str]:
        import string
        return [
            f"{l}:\\" for l in string.ascii_uppercase
            if os.path.exists(f"{l}:\\")
        ]

    # ── Populate ─────────────────────────────────────
    def _populate_defaults(self):
        self.tree.clear()
        self._custom_root_path = None

        # Akses Cepat
        quick = QTreeWidgetItem(self.tree, ["⚡  Akses Cepat"])
        quick.setData(0, Qt.ItemDataRole.UserRole, QUICK_ACCESS_MARKER)
        quick.setExpanded(True)
        home = os.path.expanduser("~")
        username = os.path.basename(home.rstrip("\\/")) or home
        for label, path in [
            (f"👤  {username}", home),
            ("🖼️  Gambar",  os.path.join(home, "Pictures")),
            ("🖥️  Desktop", os.path.join(home, "Desktop")),
            ("📥  Unduhan", os.path.join(home, "Downloads")),
            ("📄  Dokumen", os.path.join(home, "Documents")),
            ("🎞️  Video", os.path.join(home, "Videos")),
            ("🎵  Musik", os.path.join(home, "Music")),
        ]:
            if os.path.exists(path):
                item = QTreeWidgetItem(quick, [label])
                item.setData(0, Qt.ItemDataRole.UserRole, path)
                if self._has_subfolders(path):
                    QTreeWidgetItem(item, ["__placeholder__"])

        # Drive — header bisa diklik, menampilkan daftar drive di panel kanan
        drives_item = QTreeWidgetItem(self.tree, ["💾  Drive"])
        drives_item.setData(0, Qt.ItemDataRole.UserRole, DRIVES_MARKER)
        drives_item.setExpanded(True)

        for drive in self._get_drives():
            item = QTreeWidgetItem(drives_item, [f"💿  {drive}"])
            item.setData(0, Qt.ItemDataRole.UserRole, drive)
            if self._has_subfolders(drive):
                QTreeWidgetItem(item, ["__placeholder__"])

    def populate(self, root_path: str):
        self.tree.clear()
        self._custom_root_path = root_path
        name = os.path.basename(root_path) or root_path
        root_item = QTreeWidgetItem(self.tree, [f"📂  {name}"])
        root_item.setData(0, Qt.ItemDataRole.UserRole, root_path)
        root_item.setExpanded(True)
        self._add_subfolders(root_item, root_path)

    def export_state(self) -> dict:
        # Simpan tuple (indeks_top_level, path) untuk menghindari ambiguitas Akses Cepat vs Drive
        expanded_data: list[tuple[int, str]] = []
        selected_data: tuple[int, str] | None = None

        curr = self.tree.currentItem()
        if curr:
            path = curr.data(0, Qt.ItemDataRole.UserRole)
            # Cari index top level untuk item yang dipilih
            t_idx = -1
            tmp = curr
            while tmp:
                if not tmp.parent():
                    for i in range(self.tree.topLevelItemCount()):
                        if tmp == self.tree.topLevelItem(i):
                            t_idx = i; break
                tmp = tmp.parent()
                if t_idx != -1: break
            if path:
                selected_data = (t_idx, path)

        def walk(item: QTreeWidgetItem, top_idx: int):
            path = item.data(0, Qt.ItemDataRole.UserRole)
            if path and item.isExpanded():
                expanded_data.append((top_idx, path))
            for i in range(item.childCount()):
                walk(item.child(i), top_idx)

        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i), i)

        return {
            "custom_root_path": self._custom_root_path,
            "expanded_data": expanded_data,
            "selected_data": selected_data,
            "scroll_x": self.tree.horizontalScrollBar().value(),
            "scroll_y": self.tree.verticalScrollBar().value(),
        }

    def restore_state(self, state: dict):
        if not isinstance(state, dict):
            return

        custom_root_path = state.get("custom_root_path")
        if isinstance(custom_root_path, str) and custom_root_path and os.path.isdir(custom_root_path):
            self.populate(custom_root_path)
        else:
            self._populate_defaults()

        # Ambil data ekspansi (mendukung format lama expanded_paths atau format baru expanded_data)
        expanded_items = state.get("expanded_data") or []
        
        # Sort berdasarkan kedalaman path agar ekspansi berurutan dari root ke leaf
        expanded_items.sort(key=lambda x: x[1].count("\\") if isinstance(x, (list, tuple)) else 0)
        
        for item in expanded_items:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                top_idx, path = item
                self._expand_to_path(path, top_level_index=top_idx)
                target = self._find_item_by_path(path, top_level_index=top_idx)
                if target:
                    target.setExpanded(True)

        # Restorasi seleksi dengan presisi cabang
        sel_data = state.get("selected_data")
        if sel_data and isinstance(sel_data, (list, tuple)) and len(sel_data) == 2:
            t_idx, path = sel_data
            # Pastikan folder tujuan terbuka sebelum dipilih
            self._expand_to_path(path, top_level_index=t_idx)
            item = self._find_item_by_path(path, top_level_index=t_idx)
            if item:
                self.tree.setCurrentItem(item)
                self.folder_selected.emit(path)
        else:
            # Fallback untuk format lama
            old_path = state.get("selected_path")
            if old_path: self.select_path(old_path)

        scroll_x = state.get("scroll_x", 0)
        scroll_y = state.get("scroll_y", 0)
        if isinstance(scroll_x, int) and isinstance(scroll_y, int):
            self.tree.horizontalScrollBar().setValue(scroll_x)
            self.tree.verticalScrollBar().setValue(scroll_y)

    def select_path(self, path: str):
        if not isinstance(path, str) or not path:
            return

        norm_target = os.path.normpath(path).lower()

        # 1. Jika item yang dipilih sekarang sudah benar jalurnya, abaikan.
        curr = self.tree.currentItem()
        if curr:
            u_data = curr.data(0, Qt.ItemDataRole.UserRole)
            if u_data and not str(u_data).startswith("__"):
                if os.path.normpath(str(u_data)).lower() == norm_target:
                    return

        # 2. Tentukan indeks cabang prioritas (Drive untuk path fisik)
        pref_idx = -1
        if not path.startswith("__"):
            for i in range(self.tree.topLevelItemCount()):
                if self.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) == DRIVES_MARKER:
                    pref_idx = i; break

        # 3. Cari apakah item sudah ada di tree
        item = self._find_item_by_path(path)
        
        # 4. Jika item ada, buka leluhurnya. Jika tidak, lakukan lazy load di Drive.
        if item:
            # Identifikasi cabang dari item yang ditemukan
            actual_idx = -1
            tmp = item
            while tmp:
                if not tmp.parent():
                    for i in range(self.tree.topLevelItemCount()):
                        if tmp == self.tree.topLevelItem(i):
                            actual_idx = i; break
                tmp = tmp.parent()
                if actual_idx != -1: break
            self._expand_to_path(path, top_level_index=actual_idx)
        elif os.path.isdir(path) and pref_idx != -1:
            self._expand_to_path(path, top_level_index=pref_idx)
            item = self._find_item_by_path(path, top_level_index=pref_idx)

        if item:
            self.tree.setCurrentItem(item)
            self.tree.scrollToItem(item)

    def _expand_to_path(self, path: str, top_level_index: int = None):
        if top_level_index is None:
            # Jika ekspansi global, tentukan cabang prioritas (Drive untuk path fisik)
            if path and not path.startswith("__"):
                for i in range(self.tree.topLevelItemCount()):
                    if self.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole) == DRIVES_MARKER:
                        top_level_index = i; break

        ancestors = self._path_ancestors(path)
        # Hanya buka folder induk (parents), jangan buka folder tujuan itu sendiri (target)
        for ancestor in ancestors[:-1]: 
            item = self._find_item_by_path(ancestor, top_level_index=top_level_index)
            if item:
                # FIX: Mencegah ekspansi otomatis pada shortcut Akses Cepat (User, Pictures, dll).
                # Kita biarkan folder favorit tersebut tetap tertutup kecuali user membukanya sendiri.
                if top_level_index == 0:
                    p = item.parent()
                    if p and not p.parent():
                        # Ini adalah anak langsung dari root 'Akses Cepat'
                        continue

                if (item.childCount() == 1 and item.child(0).text(0) == "__placeholder__"):
                    item.takeChildren()
                    self._add_subfolders(item, ancestor)
                item.setExpanded(True)

    def _path_ancestors(self, path: str) -> list[str]:
        if path in (DRIVES_MARKER, QUICK_ACCESS_MARKER):
            return [path]

        norm = os.path.normpath(path)
        drive, tail = os.path.splitdrive(norm)
        if not drive:
            return [norm]

        ancestors = [drive + os.sep]
        parts = [part for part in tail.strip("\\/").split(os.sep) if part]
        current = drive + os.sep
        for part in parts:
            current = os.path.join(current, part)
            ancestors.append(current)
        return ancestors

    def _find_item_by_path(self, path: str, top_level_index: int = None) -> QTreeWidgetItem | None:
        matches = []
        if path is None:
            return None

        # Normalisasi path (Windows case-insensitive)
        target = os.path.normpath(path).lower() if not path.startswith("__") else path

        def walk(item: QTreeWidgetItem, top_idx: int):
            u_data = item.data(0, Qt.ItemDataRole.UserRole)
            u_norm = os.path.normpath(u_data).lower() if u_data and not str(u_data).startswith("__") else u_data
            if u_norm == target:
                matches.append((item, top_idx))
            for idx in range(item.childCount()):
                walk(item.child(idx), top_idx)

        # Jika top_level_index ditentukan, batasi pencarian HANYA pada cabang tersebut
        if top_level_index is not None and top_level_index < self.tree.topLevelItemCount():
            walk(self.tree.topLevelItem(top_level_index), top_level_index)
        else:
            for i in range(self.tree.topLevelItemCount()):
                walk(self.tree.topLevelItem(i), i)

        if not matches:
            return None
        if len(matches) == 1:
            return matches[0][0]

        # STRATEGI SELEKSI CERDAS (Menangani Jalur Ganda)

        # 1. Identifikasi cabang aktif saat ini
        curr = self.tree.currentItem()
        curr_branch = -1
        if curr:
            tmp = curr
            while tmp:
                if not tmp.parent():
                    for i in range(self.tree.topLevelItemCount()):
                        if tmp == self.tree.topLevelItem(i):
                            curr_branch = i; break
                tmp = tmp.parent()
                if curr_branch != -1: break
        
        # 2. PRIORITAS UTAMA: Jika ada kecocokan di cabang yang sedang aktif, gunakan itu!
        # Ini mengunci folder "User" di Akses Cepat agar tidak melompat ke Drive.
        if curr_branch != -1:
            for m, idx in matches:
                if idx == curr_branch: return m

        # 3. Prioritaskan item yang memang sedang dipilih secara fisik
        for m, idx in matches:
            if m == curr: return m

        # 4. Jika pencarian global (startup/gallery sync) dan belum ada cabang aktif,
        # PRIORITASKAN DRIVE (index > 0) untuk jalur fisik.
        if not target.startswith("__"):
            for m, idx in matches:
                if idx > 0: return m

        # 5. Prioritaskan item yang sudah terbuka (expanded)
        for m, idx in matches:
            if m.isExpanded(): return m

        return matches[0][0]

    def _add_subfolders(self, parent_item: QTreeWidgetItem, path: str):
        try:
            entries = sorted([
                e for e in os.scandir(path)
                if e.is_dir() and not e.name.startswith('.')
            ], key=lambda e: e.name.lower())
            for entry in entries[:200]:
                child = QTreeWidgetItem(parent_item, [f"📁  {entry.name}"])
                child.setData(0, Qt.ItemDataRole.UserRole, entry.path)
                if self._has_subfolders(entry.path):
                    QTreeWidgetItem(child, ["__placeholder__"])
        except (PermissionError, OSError):
            pass

    # ── Slot: item clicked ───────────────────────────
    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not path:
            return
        # Header khusus (Drive/Akses Cepat)
        if path in (DRIVES_MARKER, QUICK_ACCESS_MARKER):
            self.folder_selected.emit(path)
        # Folder normal
        elif os.path.isdir(path):
            self.folder_selected.emit(path)

    # ── Slot: item expanded (arrow click) ───────────
    def _on_item_expanded(self, item: QTreeWidgetItem):
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not path or path == DRIVES_MARKER:
            return
        if not os.path.isdir(path):
            return
        if (item.childCount() == 1 and
                item.child(0).text(0) == "__placeholder__"):
            item.takeChildren()
            self._add_subfolders(item, path)

    def _open_folder(self):
        from PySide6.QtWidgets import QFileDialog
        path = QFileDialog.getExistingDirectory(self, "Pilih Folder")
        if path:
            self.populate(path)
            self.folder_selected.emit(path)


# ── Clickable Label for Zoom ─────────────────────────────────────────────────
class ClickableLabel(QLabel):
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
            # Hanya ubah kursor jadi menggenggam jika gambar bisa di-zoom/drag
            if getattr(self, "zoom_enabled", False):
                self.setCursor(QCursor(Qt.CursorShape.ClosedHandCursor))
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            # Jika pergerakan lebih dari 5 pixel, aktifkan mode drag
            if (event.pos() - self._press_pos).manhattanLength() > 5:
                self._is_drag_mode = True
            
            delta = event.pos() - self._last_pos
            self.dragged.emit(delta)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if not self._is_drag_mode:
                # Klik akan memicu siklus zoom; kursor diatur ulang oleh fungsi load()
                self.clicked_at.emit(event.pos())
            elif getattr(self, "zoom_enabled", False):
                # Jika selesai drag, kembalikan ke tangan terbuka
                self.setCursor(QCursor(Qt.CursorShape.OpenHandCursor))
        super().mouseReleaseEvent(event)


# ── Preview Widget ───────────────────────────────────────────────────────────
class PreviewWidget(QWidget):
    def __init__(self):
        super().__init__()
        self._zoom_level = 0  # 0: Fit, 1: 50%, 2: 100%
        self.setMinimumHeight(120)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header.setObjectName("toolbar")
        header.setFixedHeight(28)
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(8, 0, 8, 0)
        lbl = QLabel("🖼️  Preview")
        lbl.setObjectName("labelMuted")
        h_layout.addWidget(lbl)
        layout.addWidget(header)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setObjectName("previewArea")

        self.img_label = ClickableLabel()
        self.img_label.clicked_at.connect(self._on_click_zoom)
        self.img_label.dragged.connect(self._on_drag)
        
        self.img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.img_label.setStyleSheet(
            "color: #5a5a90; font-size: 11px; border: none;"
        )
        self.img_label.setText("Pilih foto untuk preview")

        self.scroll_area.setWidget(self.img_label)
        layout.addWidget(self.scroll_area)

        self.name_label = QLabel("")
        self.name_label.setObjectName("labelMuted")
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_label.setWordWrap(True)
        self.name_label.setContentsMargins(6, 3, 6, 4)
        layout.addWidget(self.name_label)

        self._current_path = None
        self._last_pixmap_size = QPoint(0, 0)

    def _on_click_zoom(self, pos: QPoint):
        if not self._current_path or not self.img_label.pixmap():
            return

        # Hitung koordinat relatif terhadap gambar sebelum zoom berubah
        label_w, label_h = self.img_label.width(), self.img_label.height()
        pix_w, pix_h = self.img_label.pixmap().width(), self.img_label.pixmap().height()
        
        offset_x = (label_w - pix_w) // 2
        offset_y = (label_h - pix_h) // 2
        
        rel_x = (pos.x() - offset_x) / pix_w
        rel_y = (pos.y() - offset_y) / pix_h

        # Siklus zoom: Fit -> 50% -> 100%
        self._zoom_level = (self._zoom_level + 1) % 3
        self.load(self._current_path)

        # Pusatkan ke titik klik jika tidak dalam mode Fit
        if self._zoom_level > 0:
            self.img_label.adjustSize()
            new_pix_w = self.img_label.pixmap().width()
            new_pix_h = self.img_label.pixmap().height()
            
            target_x = int(rel_x * new_pix_w)
            target_y = int(rel_y * new_pix_h)
            
            view_w = self.scroll_area.viewport().width()
            view_h = self.scroll_area.viewport().height()
            
            self.scroll_area.horizontalScrollBar().setValue(target_x - view_w // 2)
            self.scroll_area.verticalScrollBar().setValue(target_y - view_h // 2)

    def _on_drag(self, delta: QPoint):
        if self._zoom_level == 0: return
        h_bar = self.scroll_area.horizontalScrollBar()
        v_bar = self.scroll_area.verticalScrollBar()
        h_bar.setValue(h_bar.value() - delta.x())
        v_bar.setValue(v_bar.value() - delta.y())
        # Update posisi terakhir agar pergerakan halus
        self.img_label._last_pos = self.img_label.mapFromGlobal(QCursor.pos())

    def load(self, path: str):
        self._current_path = path
        self.name_label.setText(os.path.basename(path))
        try:
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                w, h = self.scroll_area.width() - 4, self.scroll_area.height() - 4

                if self._zoom_level == 0:
                    # Mode Fit: Selalu muat di dalam area pratinjau
                    self.img_label.setCursor(Qt.CursorShape.PointingHandCursor)
                    scaled = pixmap.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio, 
                                         Qt.TransformationMode.SmoothTransformation)
                elif self._zoom_level == 1:
                    # Mode 50%: Bisa di-drag
                    self.img_label.setCursor(Qt.CursorShape.OpenHandCursor)
                    scaled = pixmap.scaled(pixmap.size() * 0.5, Qt.AspectRatioMode.KeepAspectRatio, 
                                         Qt.TransformationMode.SmoothTransformation)
                else:
                    # Mode 100%: Ukuran asli
                    self.img_label.setCursor(Qt.CursorShape.OpenHandCursor)
                    scaled = pixmap
                
                self.img_label.setPixmap(scaled)
            else:
                self.img_label.setText("⚠️ Tidak bisa dimuat")
        except Exception as e:
            self.img_label.setText(f"Error: {e}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Hanya update scaling otomatis jika sedang dalam mode "Fit"
        if self._current_path and getattr(self, '_zoom_level', 0) == 0:
            self.load(self._current_path)
