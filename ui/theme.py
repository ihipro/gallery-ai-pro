from PySide6.QtGui import QGuiApplication
from PySide6.QtCore import Qt

def get_stylesheet(theme_name="Astro Dark"):
    # Deteksi tema sistem jika dipilih "System"
    if theme_name == "System":
        hints = QGuiApplication.styleHints()
        theme_name = "Windows Dark" if hints.colorScheme() == Qt.ColorScheme.Dark else "Windows Light"

    # Definisi Palet Warna
    palettes = {
        "Windows Light": {
            "bg": "#ffffff", "bg2": "#f3f3f3", "bg3": "#eeeeee", "bg4": "#e5e5e5",
            "accent": "#0067c0", "accent2": "#005a9e", "text": "#000000", "muted": "#666666",
            "border": "#dcdcdc", "border2": "#cccccc", "card": "#ffffff"
        },
        "Windows Dark": {
            "bg": "#191919", "bg2": "#202020", "bg3": "#2c2c2c", "bg4": "#333333",
            "accent": "#00a4ef", "accent2": "#0078d4", "text": "#ffffff", "muted": "#aaaaaa",
            "border": "#333333", "border2": "#444444", "card": "#202020"
        },
        "Astro Dark": {
            "bg": "#07070f", "bg2": "#0d0d1a", "bg3": "#141425", "bg4": "#1c1c30",
            "accent": "#a78bfa", "accent2": "#60a5fa", "text": "#e0e0f0", "muted": "#5a5a90",
            "border": "#222235", "border2": "#303050", "card": "#10101e",
        },
        "Slate Classic": { 
            "bg": "#1a1b26", "bg2": "#24283b", "bg3": "#414868", "bg4": "#565f89",
            "accent": "#7aa2f7", "accent2": "#bb9af7", "text": "#a9b1d6", "muted": "#565f89",
            "border": "#24283b", "border2": "#414868", "card": "#24283b"
        },
        "Cyber Slate": {
            "bg": "#0f172a", "bg2": "#1e293b", "bg3": "#334155", "bg4": "#475569",
            "accent": "#38bdf8", "accent2": "#818cf8", "text": "#f8fafc", "muted": "#94a3b8",
            "border": "#1e293b", "border2": "#334155", "card": "#1e293b",
            "btn_open": "#38bdf8", "btn_open_txt": "#0f172a",
            "btn_add": "#334155", "btn_ai": "#818cf8"
        },
        "OLED Deep Black": {
            "bg": "#000000", "bg2": "#0a0a0a", "bg3": "#121212", "bg4": "#1a1212",
            "accent": "#38bdf8", "accent2": "#a1a1aa", "text": "#ffffff", "muted": "#71717a",
            "border": "#27272a", "border2": "#3f3f46", "card": "#09090b",
            "btn_open": "#ffffff", "btn_open_txt": "#000000",
            "btn_add": "#121212", "btn_ai": "#38bdf8"
        },
        "Snow White": {
            "bg": "#ffffff", "bg2": "#f8fafc", "bg3": "#f1f5f9", "bg4": "#e2e8f0",
            "accent": "#3b82f6", "accent2": "#6366f1", "text": "#0f172a", "muted": "#64748b",
            "border": "#e2e8f0", "border2": "#cbd5e1", "card": "#f8fafc",
            "btn_open": "#3b82f6", "btn_open_txt": "#ffffff",
            "btn_add": "#f1f5f9", "btn_ai": "#8b5cf6"
        }
    }

    p = palettes.get(theme_name, palettes["Astro Dark"])

    return f"""
/* ── Global ─────────────────────────────── */
QWidget {{
    background-color: {p['bg']};
    color: {p['text']};
    font-family: 'DM Sans', 'Segoe UI', sans-serif;
    font-size: 12px;
    outline: none;
}}

QAbstractItemView, QTreeView, QListView {{
    selection-background-color: {p['accent']};
    selection-background-color: {p['accent']}; /* Double define to ensure override */
    selection-color: #ffffff;
    alternate-background-color: transparent;
    show-decoration-selected: 1;
    outline: none;
}}

QMainWindow {{
    background-color: {p['bg']};
}}

/* ── Scrollbar ───────────────────────────── */
QScrollBar:vertical {{
    background: {p['bg2']};
    width: 6px;
    border-radius: 3px;
}}
QScrollBar::handle:vertical {{
    background: {p['border2']};
    border-radius: 3px;
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{
    background: {p['accent']};
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    background: {p['bg2']};
    height: 6px;
    border-radius: 3px;
}}
QScrollBar::handle:horizontal {{
    background: {p['border2']};
    border-radius: 3px;
}}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* ── Splitter ────────────────────────────── */
QSplitter::handle {{
    background-color: {p['border']};
}}
QSplitter::handle:horizontal {{
    width: 1px;
}}
QSplitter::handle:vertical {{
    height: 1px;
}}
QSplitter::handle:hover {{
    background-color: {p['accent']};
}}

/* ── Sidebar (nav icons) ─────────────────── */
#sidebar {{
    background-color: {p['bg']};
    border-right: 1px solid {p['border']};
    min-width: 52px;
    max-width: 52px;
}}

/* ── Left panel (folder tree + preview) ──── */
#leftPanel {{
    background-color: {p['bg2']};
    border-right: 1px solid {p['border']};
}}

/* ── Toolbar ─────────────────────────────── */
#toolbar {{
    background-color: {p['bg2']};
    border-bottom: 1px solid {p['border']};
    padding: 6px 12px;
    min-height: 44px;
    max-height: 44px;
}}

/* ── Statusbar ───────────────────────────── */
QStatusBar {{
    background-color: {p['bg']};
    border-top: 1px solid {p['border']};
    color: {p['muted']};
    font-size: 11px;
    padding: 2px 8px;
}}

/* ── Buttons ─────────────────────────────── */
QPushButton {{
    background-color: {p['bg3']};
    border: 1px solid {p['border2']};
    border-radius: 6px;
    color: {p['text']};
    padding: 5px 12px;
    font-size: 12px;
    min-height: 22px;
}}
QPushButton:hover {{
    background-color: {p['bg4']};
    border-color: {p['accent']};
}}
QPushButton:pressed {{
    background-color: {p['border2']};
}}
QPushButton:disabled {{
    opacity: 0.4;
    color: {p['muted']};
    border-color: {p['border']};
}}

QPushButton#btnPrimary {{
    background-color: {p['accent']};
    border: 1px solid {p['accent2']};
    color: #ffffff;
    font-weight: 600;
}}
QPushButton#btnPrimary:hover {{
    background-color: {p['accent2']};
}}

QPushButton#btnAI {{
    background-color: {p['bg']};
    border: 1px solid {p['border2']};
    color: {p['accent']};
    font-weight: 600;
}}
QPushButton#btnAI:hover {{
    background-color: {p['bg2']};
    border-color: {p['accent']};
}}

QPushButton#btnDanger {{
    border-color: rgba(248, 113, 113, 0.4);
    color: #f87171;
}}
QPushButton#btnDanger:hover {{
    background-color: rgba(248, 113, 113, 0.1);
    border-color: #f87171;
}}

/* ── Sidebar nav button ──────────────────── */
QPushButton#navBtn {{
    background-color: transparent;
    border: none;
    border-radius: 8px;
    color: {p['muted']};
    font-size: 20px;
    padding: 8px;
    min-width: 36px;
    max-width: 36px;
    min-height: 36px;
    max-height: 36px;
}}
QPushButton#navBtn:hover {{
    background-color: {p['bg3']};
    color: {p['text']};
}}
QPushButton#navBtn[active="true"] {{
    background-color: {p['bg4']};
    color: {p['accent']};
    border: 1px solid {p['border2']};
}}

/* ── Tree Widget (folder tree) ───────────── */
QTreeWidget {{
    background-color: {p['bg2']};
    border: none;
    color: {p['text']};
    font-size: 12px;
    outline: 0;
}}
QTreeWidget::item {{
    padding: 4px 6px;
    border-radius: 4px;
}}
QTreeWidget::item:hover {{
    background-color: {p['bg4']};
}}

/* Perbaikan Highlight: Item dan Branch harus memiliki gaya yang sama agar tidak terlihat terpisah */
QTreeWidget::item:selected, 
QTreeWidget::branch:selected {{
    background-color: {p['accent']};
    selection-background-color: {p['accent']};
    color: #ffffff;
}}
QTreeWidget::item:selected:!active, 
QTreeWidget::branch:selected:!active {{
    background-color: {p['accent']};
    selection-background-color: {p['accent']};
    color: #ffffff;
}}
/* QTreeWidget::branch — intentionally NOT overridden here so Qt's
   default expand/collapse arrows remain visible. Background is
   inherited from QTreeWidget background-color above. */

/* ── Search box ──────────────────────────── */
QLineEdit {{
    background-color: {p['bg3']};
    border: 1px solid {p['border2']};
    border-radius: 6px;
    color: {p['text']};
    padding: 5px 10px;
    font-size: 12px;
}}
QLineEdit:focus {{
    border-color: {p['accent2']};
}}
QLineEdit::placeholder {{
    color: {p['muted']};
}}

/* ── ComboBox ────────────────────────────── */
QComboBox {{
    background-color: {p['bg3']};
    border: 1px solid {p['border2']};
    border-radius: 6px;
    color: {p['text']};
    padding: 5px 10px;
    font-size: 12px;
    min-width: 120px;
}}
QComboBox:hover {{
    border-color: {p['accent']};
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox QAbstractItemView {{
    background-color: {p['bg3']};
    border: 1px solid {p['border2']};
    color: {p['text']};
    selection-background-color: {p['accent']}33;
}}

/* ── Label ───────────────────────────────── */
QLabel {{
    background: transparent;
    color: {p['text']};
}}
QLabel#labelMuted {{
    color: {p['muted']};
    font-size: 11px;
}}
QLabel#labelAccent {{
    color: {p['accent']};
    font-weight: 700;
}}

/* ── ProgressBar ─────────────────────────── */
QProgressBar {{
    background-color: {p['bg3']};
    border: none;
    border-radius: 2px;
    height: 3px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {p['accent']}, stop:1 {p['accent2']});
    border-radius: 2px;
}}

/* ── Tooltip ─────────────────────────────── */
QToolTip {{
    background-color: {p['bg4']};
    border: 1px solid {p['border2']};
    color: {p['text']};
    padding: 4px 8px;
    border-radius: 4px;
    font-size: 11px;
}}

/* ── Menu ────────────────────────────────── */
QMenu {{
    background-color: {p['bg3']};
    border: 1px solid {p['border2']};
    border-radius: 8px;
    padding: 4px;
    color: {p['text']};
}}
QMenu::item {{
    padding: 6px 24px 6px 12px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background-color: {p['accent']}26;
    color: {p['accent']};
}}
QMenu::separator {{
    height: 1px;
    background-color: {p['border']};
    margin: 4px 8px;
}}

/* ── Tab (untuk panel detail) ────────────── */
QTabWidget::pane {{
    border: none;
    background-color: {p['bg2']};
}}
QTabBar::tab {{
    background-color: transparent;
    border: none;
    color: {p['muted']};
    padding: 6px 14px;
    font-size: 12px;
    border-radius: 6px;
    margin: 2px;
}}
QTabBar::tab:hover {{
    color: {p['text']};
    background-color: {p['bg3']};
}}
QTabBar::tab:selected {{
    background-color: {p['bg4']};
    color: {p['accent']};
    border: 1px solid {p['border2']};
}}

/* ── Frame/Card ──────────────────────────── */
QFrame#card {{
    background-color: {p['card']};
    border: 1px solid {p['border']};
    border-radius: 10px;
}}
QFrame#card:hover {{
    background-color: {p['bg3']};
    border-color: {p['accent2']};
}}
QFrame#card[selected="true"] {{
    background-color: {p['accent']}33;
    border: 2px solid {p['accent']};
}}
QFrame#card[selected="true"]:!active {{
    background-color: {p['accent']}1A;
}}

/* ── Row Selection (List View) ───────────── */
#folderRow:hover, #listRow:hover {{
    background-color: {p['bg3']};
}}
#folderRow[selected="true"], #listRow[selected="true"] {{
    background-color: {p['accent']}33;
    border-left: 3px solid {p['accent']};
}}
#folderRow[selected="true"]:!active, #listRow[selected="true"]:!active {{
    background-color: {p['accent']}1A;
    border-left: 3px solid {p['accent']}88;
}}

/* ── Custom Object Styling ──────────────── */
#galleryGrid {{
    background-color: {p['bg']};
}}
#progressContainer {{
    background-color: {p['bg2']};
}}
#previewArea {{
    background-color: {p['bg2']};
}}
#thumbPlaceholder {{
    background-color: {p['bg3']};
    border-radius: 6px;
}}
"""