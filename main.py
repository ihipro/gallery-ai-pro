import sys
from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Gallery AI Pro")
    app.setOrganizationName("GalleryAIPro")
    # Qt 6 enables high-DPI automatically — AA_UseHighDpiPixmaps is deprecated/removed

    window = MainWindow()
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()