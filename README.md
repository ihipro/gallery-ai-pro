Gallery AI Pro

Gallery AI Pro adalah aplikasi manajemen foto desktop berbasis Python dan PySide6 yang dirancang untuk mengelola, mencari, dan mengorganisir koleksi foto besar secara cerdas. Aplikasi ini menggabungkan performa aplikasi native dengan kapabilitas AI modern (Gemini, OpenAI, dan Anthropic) untuk fitur auto-tagging dan pengenalan wajah (model lokal).

Fitur Utama
- AI Auto-Tagging: Integrasi API dengan Google Gemini, OpenAI, dan Anthropic untuk kategorisasi foto otomatis (22+ kategori tag seperti latar belakang, mood, aktivitas, dll).
- Local Face Recognition: Deteksi dan pengenalan wajah yang berjalan 100% di mesin lokal untuk menjaga privasi data.
- Pencarian Bahasa Alami (NL Search): Cari foto menggunakan deskripsi kalimat biasa (contoh: "foto keluarga saat liburan di pantai").
- Manajemen Metadata EXIF: Membaca dan memetakan data teknis kamera, lensa, serta koordinat GPS ke dalam peta interaktif.
- Deteksi Duplikat: Mencari file foto yang identik (Hash-based) maupun serupa secara visual (Perceptual Hash).
- OCR (Optical Character Recognition): Menggunakan OCR.space API dan Gemini API, ekstraksi teks dari dokumen, struk, atau papan nama di dalam foto.
- High Performance: Arsitektur asynchronous untuk pemindaian folder besar tanpa membuat UI freeze.

Arsitektur Teknis
- Language: Python 3.10+
- UI Framework: PySide6 (Qt for Python)
- Database: SQLite dengan WAL mode untuk integritas data.
- Image Processing: Pillow (PIL) & OpenCV.
- Theme Engine: Sistem tema dinamis (Windows Native, Astro Dark, OLED, Slate).

Persiapan & Instalasi
1. Clone repositori:

   ==bash==
   
   git clone https://github.com/username/GalleryAIPro.git
   cd GalleryAIPro

3. Instal dependensi:

   ==bash==
   
   pip install -r requirements.txt

5. Jalankan aplikasi:

   ==bash==
   
   python main.py
   

Catatan Penggunaan
Untuk menggunakan fitur Auto-Tagging, Anda perlu memasukkan API Key (Gemini/OpenAI) di panel Pengaturan di dalam aplikasi. Semua metadata dan thumbnail akan disimpan secara lokal di folder /data.
