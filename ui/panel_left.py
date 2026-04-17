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
from PySide6.QtGui import QPixmap, QPainter, QColor, QPolygonF, QCursor
import os

# Special marker emitted when user clicks the "💾 Drive" header
DRIVES_MARKER = "__drives__"


# ── Custom proxy style: always-visible tree arrows ───────────────────────────
class TreeArrowStyle(QProxyStyle):
    """
    Draws tree branch arrows in a visible color so they are always
    shown against the dark background — not just on hover.
    """
    ARROW_NORMAL   = QColor("#6b6b9a")   # muted — always visible
    ARROW_SELECTED = QColor("#a78bfa")   # accent — on selected/hovered row

    def drawPrimitive(self, element, option, painter, widget=None):
        if element == QStyle.PrimitiveElement.PE_IndicatorBranch:
            # Only draw arrow if this item HAS children
            if not (option.state & QStyle.StateFlag.State_Children):
                return   # leaf node — draw nothing

            r    = option.rect
            cx   = r.x() + r.width()  / 2.0
            cy   = r.y() + r.height() / 2.0
            half = min(r.width(), r.height()) * 0.30

            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)

            # Always visible — highlight on hover
            if option.state & QStyle.StateFlag.State_MouseOver:
                painter.setBrush(self.ARROW_SELECTED)
            else:
                painter.setBrush(self.ARROW_NORMAL)

            if option.state & QStyle.StateFlag.State_Open:
                # Expanded → pointing down ▼
                poly = QPolygonF([
                    QPointF(cx - half, cy - half * 0.5),
                    QPointF(cx + half, cy - half * 0.5),
                    QPointF(cx,        cy + half),
                ])
            else:
                # Collapsed → pointing right ▶
                poly = QPolygonF([
                    QPointF(cx - half * 0.5, cy - half),
                    QPointF(cx + half,        cy),
                    QPointF(cx - half * 0.5, cy + half),
                ])

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
        expanded_paths: list[str] = []
        selected_path = None

        current = self.tree.currentItem()
        if current:
            selected_path = current.data(0, Qt.ItemDataRole.UserRole)

        def walk(item: QTreeWidgetItem):
            path = item.data(0, Qt.ItemDataRole.UserRole)
            if path and item.isExpanded():
                expanded_paths.append(path)
            for i in range(item.childCount()):
                walk(item.child(i))

        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))

        return {
            "custom_root_path": self._custom_root_path,
            "expanded_paths": expanded_paths,
            "selected_path": selected_path,
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

        expanded_paths = [
            path for path in state.get("expanded_paths", [])
            if isinstance(path, str) and path
        ]
        expanded_paths.sort(key=lambda path: path.count("\\"))
        for path in expanded_paths:
            self._expand_to_path(path)

        selected_path = state.get("selected_path")
        if isinstance(selected_path, str) and selected_path:
            item = self._find_item_by_path(selected_path)
            if item:
                self.tree.setCurrentItem(item)

        scroll_x = state.get("scroll_x", 0)
        scroll_y = state.get("scroll_y", 0)
        if isinstance(scroll_x, int) and isinstance(scroll_y, int):
            self.tree.horizontalScrollBar().setValue(scroll_x)
            self.tree.verticalScrollBar().setValue(scroll_y)

    def select_path(self, path: str):
        if not isinstance(path, str) or not path:
            return

        if path == DRIVES_MARKER:
            item = self._find_item_by_path(DRIVES_MARKER)
            if item:
                self.tree.setCurrentItem(item)
                self.tree.scrollToItem(item)
            return

        if not os.path.isdir(path):
            parent = os.path.dirname(path)
            if not parent:
                return
            path = parent

        self._expand_to_path(path)
        item = self._find_item_by_path(path)
        if not item and os.path.isdir(path):
            self.populate(path)
            item = self._find_item_by_path(path)

        if item:
            self.tree.setCurrentItem(item)
            self.tree.scrollToItem(item)

    def _expand_to_path(self, path: str):
        for ancestor in self._path_ancestors(path):
            item = self._find_item_by_path(ancestor)
            if item:
                if (item.childCount() == 1 and item.child(0).text(0) == "__placeholder__"):
                    item.takeChildren()
                    self._add_subfolders(item, ancestor)
                item.setExpanded(True)

    def _path_ancestors(self, path: str) -> list[str]:
        if path == DRIVES_MARKER:
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

    def _find_item_by_path(self, path: str) -> QTreeWidgetItem | None:
        def walk(item: QTreeWidgetItem):
            if item.data(0, Qt.ItemDataRole.UserRole) == path:
                return item
            for idx in range(item.childCount()):
                found = walk(item.child(idx))
                if found:
                    return found
            return None

        for i in range(self.tree.topLevelItemCount()):
            found = walk(self.tree.topLevelItem(i))
            if found:
                return found
        return None

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
        # "💾 Drive" header → show drive list in right panel
        if path == DRIVES_MARKER:
            self.folder_selected.emit(DRIVES_MARKER)
        # Normal folder or drive letter → load gallery
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
        self._last_pos = QPoint()
        self._press_pos = QPoint()
        self._is_drag_mode = False

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.pos()
            self._last_pos = event.pos()
            self._is_drag_mode = False
            # Ubah kursor jadi tangan menggenggam saat klik/drag
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
            self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            # Hanya trigger zoom jika user TIDAK sedang melakukan drag
            if not self._is_drag_mode:
                self.clicked_at.emit(event.pos())
        super().mouseReleaseEvent(event)


# ── Preview Widget ───────────────────────────────────────────────────────────
class PreviewWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(120)
        self._zoom_level = 0  # 0: Fit, 1: 50%, 2: 100%
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
        self.scroll_area.setStyleSheet("background-color: #0d0d1a; border: none;")

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

        old_level = self._zoom_level
        # Hitung koordinat relatif terhadap gambar sebelum zoom berubah
        # Karena alignment center, kita cari offset gambar di dalam label
        label_w, label_h = self.img_label.width(), self.img_label.height()
        pix_w, pix_h = self.img_label.pixmap().width(), self.img_label.pixmap().height()
        
        offset_x = (label_w - pix_w) // 2
        offset_y = (label_h - pix_h) // 2
        
        # Titik klik relatif terhadap top-left gambar (0.0 - 1.0)
        rel_x = (pos.x() - offset_x) / pix_w
        rel_y = (pos.y() - offset_y) / pix_h

        # Siklus zoom
        self._zoom_level = (self._zoom_level + 1) % 3
        self.load(self._current_path)

        # Jika masuk ke mode zoom (50% atau 100%), pusatkan ke titik klik
        if self._zoom_level > 0:
            # Paksa update layout agar scrollbar range terupdate
            self.img_label.adjustSize()
            
            new_pix_w = self.img_label.pixmap().width()
            new_pix_h = self.img_label.pixmap().height()
            
            target_x = int(rel_x * new_pix_w)
            target_y = int(rel_y * new_pix_h)
            
            # Hitung posisi scrollbar agar target_x/y ada di tengah viewport
            view_w = self.scroll_area.viewport().width()
            view_h = self.scroll_area.viewport().height()
            
            self.scroll_area.horizontalScrollBar().setValue(target_x - view_w // 2)
            self.scroll_area.verticalScrollBar().setValue(target_y - view_h // 2)

    def _on_drag(self, delta: QPoint):
        if self._zoom_level == 0:
            return # Tidak perlu drag jika mode Fit
        
        h_bar = self.scroll_area.horizontalScrollBar()
        v_bar = self.scroll_area.verticalScrollBar()
        
        h_bar.setValue(h_bar.value() - delta.x())
        v_bar.setValue(v_bar.value() - delta.y())
        # Kita perlu mengupdate titik awal drag di ClickableLabel secara manual
        # agar pergerakan terasa smooth (non-cumulative delta)
        self.img_label._last_pos = self.img_label.mapFromGlobal(QCursor.pos())

    def load(self, path: str):
        self._current_path = path
        self.name_label.setText(os.path.basename(path))
        try:
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                if self._zoom_level == 1:
                    # Zoom 50% dari resolusi asli
                    scaled = pixmap.scaled(pixmap.size() * 0.5, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                elif self._zoom_level == 2:
                    # Zoom 100% (Resolusi Asli)
                    scaled = pixmap
                else:
                    # Zoom Fit (Default)
                    w, h = self.scroll_area.width() - 4, self.scroll_area.height() - 4
                    scaled = pixmap.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                
                self.img_label.setPixmap(scaled)
            else:
                self.img_label.setText("⚠️ Tidak bisa dimuat")
        except Exception as e:
            self.img_label.setText(f"Error: {e}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Hanya update scaling otomatis jika sedang dalam mode "Fit"
        if self._current_path and self._zoom_level == 0:
            self.load(self._current_path)
