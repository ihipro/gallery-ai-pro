import sys
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from ui.main_window import MainWindow

def main():
    # Paksa penggunaan Desktop OpenGL dan matikan emulasi D3D/ANGLE
    os.environ["QT_OPENGL"] = "desktop"
    
    # Paksa RHI (Rendering Hardware Interface) menggunakan OpenGL untuk komposisi top-level
    # Ini akan menghilangkan peringatan D3D11 dan mengaktifkan akselerasi penuh GPU Vega Anda.
    os.environ["QSG_RHI_BACKEND"] = "opengl"

    # Paksa penggunaan Desktop OpenGL untuk menghindari konflik dengan D3D11 pada QOpenGLWidget
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseDesktopOpenGL)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseOpenGLES, False) # Pastikan tidak menggunakan GLES
    
    # Sinkronisasi context antara top-level window dan child widgets
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    
    app = QApplication(sys.argv)
    app.setApplicationName("Gallery AI Pro")
    app.setOrganizationName("GalleryAIPro")
    # Qt 6 enables high-DPI automatically — AA_UseHighDpiPixmaps is deprecated/removed

    window = MainWindow()
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()