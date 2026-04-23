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
1. Salin repositori:
   ```bash
   git clone https://github.com/username/GalleryAIPro.git
   cd GalleryAIPro
   ```
2. Instal dependensi:
   ```bash
   pip install -r requirements.txt
   ```
3. Jalankan aplikasi:
   ```bash
   python main.py
   ```
   

Catatan Penggunaan
Untuk menggunakan fitur Auto-Tagging, Anda perlu memasukkan API Key (Gemini/OpenAI/Anthropic) di panel Pengaturan di dalam aplikasi. Semua metadata dan thumbnail akan disimpan secara lokal di folder /data.

---

# Gallery AI Pro (English Version)

Gallery AI Pro is a desktop photo management application based on Python and PySide6, designed to intelligently manage, search, and organize large photo collections. This application combines native performance with modern AI capabilities (Gemini, OpenAI, and Anthropic) for auto-tagging and face recognition (local model).

## Key Features
- **AI Auto-Tagging**: API integration with Google Gemini, OpenAI, and Anthropic for automatic photo categorization (22+ tag categories such as background, mood, activity, etc.).
- **Local Face Recognition**: Face detection and recognition running 100% on the local machine to ensure data privacy.
- **Natural Language Search (NL Search)**: Search for photos using natural language descriptions (e.g., "family vacation photos at the beach").
- **EXIF Metadata Management**: Reads and maps technical data of cameras, lenses, and GPS coordinates into an interactive map.
- **Duplicate Detection**: Searches for identical (Hash-based) as well as visually similar (Perceptual Hash) photo files.
- **OCR (Optical Character Recognition)**: Extraction of text from documents, receipts, or signboards within photos using OCR.space and Gemini APIs.
- **High Performance**: Asynchronous architecture for scanning large folders without freezing the UI.

## Technical Architecture
- **Language**: Python 3.10+
- **UI Framework**: PySide6 (Qt for Python)
- **Database**: SQLite with WAL mode for data integrity.
- **Image Processing**: Pillow (PIL) & OpenCV.
- **Theme Engine**: Dynamic theme system (Windows Native, Astro Dark, OLED, Slate).

## Setup & Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/username/GalleryAIPro.git
   cd GalleryAIPro
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the application:
   ```bash
   python main.py
   ```

## Usage Notes
To use the Auto-Tagging feature, you need to enter your API Key (Gemini/OpenAI/Anthropic) in the Settings panel within the application. All metadata and thumbnails are stored locally in the `/data` folder.
