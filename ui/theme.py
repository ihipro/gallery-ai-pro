DARK_THEME = """
/* ── Global ─────────────────────────────── */
QWidget {
    background-color: #07070f;
    color: #e0e0f0;
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 12px;
}

QMainWindow {
    background-color: #07070f;
}

/* ── Scrollbar ───────────────────────────── */
QScrollBar:vertical {
    background: #0d0d1a;
    width: 6px;
    border-radius: 3px;
}
QScrollBar::handle:vertical {
    background: #303050;
    border-radius: 3px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover {
    background: #a78bfa;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar:horizontal {
    background: #0d0d1a;
    height: 6px;
    border-radius: 3px;
}
QScrollBar::handle:horizontal {
    background: #303050;
    border-radius: 3px;
}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* ── Splitter ────────────────────────────── */
QSplitter::handle {
    background-color: #222235;
}
QSplitter::handle:horizontal {
    width: 1px;
}
QSplitter::handle:vertical {
    height: 1px;
}
QSplitter::handle:hover {
    background-color: #a78bfa;
}

/* ── Sidebar (nav icons) ─────────────────── */
#sidebar {
    background-color: #080813;
    border-right: 1px solid #222235;
    min-width: 52px;
    max-width: 52px;
}

/* ── Left panel (folder tree + preview) ──── */
#leftPanel {
    background-color: #0d0d1a;
    border-right: 1px solid #222235;
}

/* ── Toolbar ─────────────────────────────── */
#toolbar {
    background-color: #0d0d1a;
    border-bottom: 1px solid #222235;
    padding: 6px 12px;
    min-height: 44px;
    max-height: 44px;
}

/* ── Statusbar ───────────────────────────── */
QStatusBar {
    background-color: #080813;
    border-top: 1px solid #222235;
    color: #5a5a90;
    font-size: 11px;
    padding: 2px 8px;
}

/* ── Buttons ─────────────────────────────── */
QPushButton {
    background-color: #141425;
    border: 1px solid #303050;
    border-radius: 6px;
    color: #e0e0f0;
    padding: 5px 12px;
    font-size: 12px;
}
QPushButton:hover {
    background-color: #1c1c30;
    border-color: #a78bfa;
    color: #a78bfa;
}
QPushButton:pressed {
    background-color: #0d0d1a;
}
QPushButton:disabled {
    opacity: 0.4;
    color: #5a5a90;
    border-color: #222235;
}

QPushButton#btnPrimary {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #a78bfa, stop:1 #60a5fa);
    border: none;
    color: white;
    font-weight: 600;
}
QPushButton#btnPrimary:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #b89cfb, stop:1 #71b6fb);
    color: white;
}

QPushButton#btnAI {
    background-color: rgba(167, 139, 250, 0.1);
    border-color: rgba(167, 139, 250, 0.4);
    color: #a78bfa;
    font-weight: 600;
}
QPushButton#btnAI:hover {
    background-color: rgba(167, 139, 250, 0.2);
    border-color: #a78bfa;
}

QPushButton#btnDanger {
    border-color: rgba(248, 113, 113, 0.4);
    color: #f87171;
}
QPushButton#btnDanger:hover {
    background-color: rgba(248, 113, 113, 0.1);
    border-color: #f87171;
}

/* ── Sidebar nav button ──────────────────── */
QPushButton#navBtn {
    background-color: transparent;
    border: none;
    border-radius: 8px;
    color: #5a5a90;
    font-size: 20px;
    padding: 8px;
    min-width: 36px;
    max-width: 36px;
    min-height: 36px;
    max-height: 36px;
}
QPushButton#navBtn:hover {
    background-color: #141425;
    color: #e0e0f0;
}
QPushButton#navBtn[active="true"] {
    background-color: #1c1c30;
    color: #a78bfa;
    border: 1px solid #303050;
}

/* ── Tree Widget (folder tree) ───────────── */
QTreeWidget {
    background-color: #0d0d1a;
    border: none;
    color: #e0e0f0;
    font-size: 12px;
    outline: 0;
}
QTreeWidget::item {
    padding: 4px 6px;
    border-radius: 4px;
}
QTreeWidget::item:hover {
    background-color: #141425;
}
QTreeWidget::item:selected {
    background-color: rgba(167, 139, 250, 0.15);
    color: #c4b5fd;
}
/* QTreeWidget::branch — intentionally NOT overridden here so Qt's
   default expand/collapse arrows remain visible. Background is
   inherited from QTreeWidget background-color above. */

/* ── Search box ──────────────────────────── */
QLineEdit {
    background-color: #141425;
    border: 1px solid #303050;
    border-radius: 6px;
    color: #e0e0f0;
    padding: 5px 10px;
    font-size: 12px;
}
QLineEdit:focus {
    border-color: #60a5fa;
}
QLineEdit::placeholder {
    color: #5a5a90;
}

/* ── ComboBox ────────────────────────────── */
QComboBox {
    background-color: #141425;
    border: 1px solid #303050;
    border-radius: 6px;
    color: #e0e0f0;
    padding: 5px 10px;
    font-size: 12px;
    min-width: 120px;
}
QComboBox:hover {
    border-color: #a78bfa;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox QAbstractItemView {
    background-color: #141425;
    border: 1px solid #303050;
    color: #e0e0f0;
    selection-background-color: rgba(167, 139, 250, 0.2);
}

/* ── Label ───────────────────────────────── */
QLabel {
    background: transparent;
    color: #e0e0f0;
}
QLabel#labelMuted {
    color: #5a5a90;
    font-size: 11px;
}
QLabel#labelAccent {
    color: #a78bfa;
    font-weight: 700;
}

/* ── ProgressBar ─────────────────────────── */
QProgressBar {
    background-color: #141425;
    border: none;
    border-radius: 2px;
    height: 3px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #a78bfa, stop:1 #60a5fa);
    border-radius: 2px;
}

/* ── Tooltip ─────────────────────────────── */
QToolTip {
    background-color: #1c1c30;
    border: 1px solid #303050;
    color: #e0e0f0;
    padding: 4px 8px;
    border-radius: 4px;
    font-size: 11px;
}

/* ── Menu ────────────────────────────────── */
QMenu {
    background-color: #141425;
    border: 1px solid #303050;
    border-radius: 8px;
    padding: 4px;
    color: #e0e0f0;
}
QMenu::item {
    padding: 6px 24px 6px 12px;
    border-radius: 4px;
}
QMenu::item:selected {
    background-color: rgba(167, 139, 250, 0.15);
    color: #c4b5fd;
}
QMenu::separator {
    height: 1px;
    background-color: #222235;
    margin: 4px 8px;
}

/* ── Tab (untuk panel detail) ────────────── */
QTabWidget::pane {
    border: none;
    background-color: #0d0d1a;
}
QTabBar::tab {
    background-color: transparent;
    border: none;
    color: #5a5a90;
    padding: 6px 14px;
    font-size: 12px;
    border-radius: 6px;
    margin: 2px;
}
QTabBar::tab:hover {
    color: #e0e0f0;
    background-color: #141425;
}
QTabBar::tab:selected {
    background-color: #1c1c30;
    color: #a78bfa;
    border: 1px solid #303050;
}

/* ── Frame/Card ──────────────────────────── */
QFrame#card {
    background-color: #10101e;
    border: 1px solid #222235;
    border-radius: 10px;
}
QFrame#card:hover {
    border-color: #60a5fa;
}
"""