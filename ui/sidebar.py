from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QSpacerItem, QSizePolicy
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor


class Sidebar(QWidget):
    """Vertical icon navigation bar on the far left."""

    nav_changed = Signal(str)  # emits section name when nav button clicked

    NAV_ITEMS = [
        ("🖼️",  "gallery",    "Gallery"),
        ("🕐",  "timeline",   "Timeline"),
        ("🔍",  "search",     "Cari Foto"),
        ("👤",  "face",       "Wajah"),
        ("🗺️", "map",        "Peta GPS"),
        ("📋",  "duplicates", "Duplikat"),
        ("📊",  "stats",      "Statistik"),
    ]

    BOTTOM_ITEMS = [
        ("⚙️",  "settings",  "Pengaturan"),
    ]

    def __init__(self):
        super().__init__()
        self.setFixedWidth(52)
        self._buttons: dict[str, QPushButton] = {}
        self._active = "gallery"
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 12, 6, 12)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # App logo / title area
        logo = QWidget()
        logo.setFixedHeight(36)
        layout.addWidget(logo)
        layout.addSpacing(8)

        # Main nav buttons
        for emoji, key, tooltip in self.NAV_ITEMS:
            btn = self._make_nav_btn(emoji, key, tooltip)
            layout.addWidget(btn)
            self._buttons[key] = btn

        # Spacer pushes settings to bottom
        layout.addSpacerItem(QSpacerItem(0, 0,
            QSizePolicy.Policy.Minimum,
            QSizePolicy.Policy.Expanding))

        # Bottom buttons (settings)
        for emoji, key, tooltip in self.BOTTOM_ITEMS:
            btn = self._make_nav_btn(emoji, key, tooltip)
            layout.addWidget(btn)
            self._buttons[key] = btn

        # Set gallery as default active
        self._set_active("gallery")

    def _make_nav_btn(self, emoji: str, key: str, tooltip: str) -> QPushButton:
        btn = QPushButton(emoji)
        btn.setObjectName("navBtn")
        btn.setToolTip(tooltip)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setFixedSize(36, 36)
        btn.clicked.connect(lambda checked=False, k=key: self._on_click(k))
        return btn

    def _on_click(self, key: str):
        self._set_active(key)
        self.nav_changed.emit(key)

    def _set_active(self, key: str):
        # Remove active from previous
        if self._active in self._buttons:
            self._buttons[self._active].setProperty("active", False)
            self._buttons[self._active].style().unpolish(self._buttons[self._active])
            self._buttons[self._active].style().polish(self._buttons[self._active])

        # Set active on new
        self._active = key
        if key in self._buttons:
            self._buttons[key].setProperty("active", True)
            self._buttons[key].style().unpolish(self._buttons[key])
            self._buttons[key].style().polish(self._buttons[key])