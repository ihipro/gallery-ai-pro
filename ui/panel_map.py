from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QFrame
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtCore import Qt, QTimer, Signal, QSettings, QObject, Slot, QUrl
import json
import os
from core.database import get_all_photos, get_thumb_path, get_gps_photos_with_thumbs
from ui.panel_gallery import Lightbox

MAP_HTML = """
<!DOCTYPE html>
<html>
<head>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.4.1/dist/MarkerCluster.css" />
    <link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.4.1/dist/MarkerCluster.Default.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script src="https://unpkg.com/leaflet.markercluster@1.4.1/dist/leaflet.markercluster.js"></script>
    <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
    <style>
        body { margin: 0; padding: 0; background: #07070f; }
        #map { height: 100vh; width: 100vw; background: #07070f; }
        .leaflet-popup-content-wrapper { background: #1c1c30; color: #e0e0f0; border-radius: 8px; }
        .leaflet-popup-tip { background: #1c1c30; }
        .thumb-popup { width: 120px; text-align: center; }
        .thumb-popup img { width: 100%; border-radius: 4px; margin-bottom: 5px; cursor: pointer; transition: transform 0.2s; }
        .thumb-popup img:hover { transform: scale(1.05); }
        .thumb-popup b { font-size: 10px; display: block; word-break: break-all; }
    </style>
</head>
<body>
    <div id="map"></div>
    <script>
        var map = L.map('map', { zoomControl: false }).setView([0, 0], 2);
        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; OpenStreetMap &copy; CARTO'
        }).addTo(map);
        L.control.zoom({ position: 'bottomright' }).addTo(map);

        var pythonBridge = null;
        new QWebChannel(qt.webChannelTransport, function(channel) {
            pythonBridge = channel.objects.pythonBridge;
        });

        function openPhoto(id) {
            if (pythonBridge) pythonBridge.openPhoto(id);
        }

        var markers = L.markerClusterGroup();
        map.addLayer(markers);

        var _allPhotosRaw = []; // Source of truth untuk koordinat

        function updateMarkers(photoData, shouldFit) {
            _allPhotosRaw = photoData; // Simpan data mentah
            markers.clearLayers();
            if (!photoData || photoData.length === 0) return;

            var markerList = [];
            var boundsList = [];
            photoData.forEach(function(p) {
                if (p.lat != null && p.lng != null) {
                    var marker = L.marker([p.lat, p.lng], { photoId: p.id });
                    
                    var imgSrc = p.img_url;
                    
                    var popupContent = `
                        <div class="thumb-popup">
                            <img src="${imgSrc}" onclick="openPhoto(${p.id})" title="Klik untuk perbesar" />
                            <b>${p.name}</b>
                        </div>
                    `;
                    marker.bindPopup(popupContent);
                    markerList.push(marker);
                    boundsList.push([p.lat, p.lng]);
                }
            });

            markers.addLayers(markerList); // Batch processing (optimasi performa)
            if (shouldFit && boundsList.length > 0) {
                map.invalidateSize(); // Pastikan leaflet menghitung ulang ukuran kontainer
                map.fitBounds(boundsList, { padding: [50, 50], maxZoom: 15 });
            }
        }

        // Fungsi untuk mendapatkan ID foto yang masuk dalam area pandang saat ini
        function getVisibleIds() {
            if (!map || !_allPhotosRaw || _allPhotosRaw.length === 0) return [];
            var bounds = map.getBounds();
            var sw = bounds.getSouthWest();
            var ne = bounds.getNorthEast();
            
            var visibleIds = [];
            _allPhotosRaw.forEach(function(p) {
                var lat = parseFloat(p.lat);
                var lng = parseFloat(p.lng);
                if (!isNaN(lat) && !isNaN(lng)) {
                    if (lat >= sw.lat && lat <= ne.lat && lng >= sw.lng && lng <= ne.lng) {
                        visibleIds.push(p.id);
                    }
                }
            });
            return visibleIds;
        }
    </script>
</body>
</html>
"""

class FilterChip(QPushButton):
    def __init__(self, text, count=0, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        label = f"{text} ({count})" if count > 0 else text
        self.setText(label)
        self.setFixedHeight(24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("""
            QPushButton {
                background: #141425;
                border: 1px solid #222235;
                border-radius: 12px;
                color: #5a5a90;
                font-size: 11px;
                padding: 0 12px;
            }
            QPushButton:hover {
                border-color: #a78bfa;
                color: #e0e0f0;
            }
            QPushButton:checked {
                background: rgba(167, 139, 250, 0.15);
                border-color: #a78bfa;
                color: #c4b5fd;
                font-weight: bold;
            }
        """)

class MapBridge(QObject):
    """Jembatan komunikasi dari JavaScript (Peta) ke Python."""
    photo_clicked = Signal(int)

    @Slot(int)
    def openPhoto(self, photo_id):
        self.photo_clicked.emit(photo_id)

class MapPanel(QWidget):
    geocode_requested = Signal(list)

    def __init__(self):
        super().__init__()
        self._is_loaded = False
        self._all_photos_gps = []
        self._selected_country = None
        self._selected_city = None
        
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Header/Title
        header = QWidget()
        header.setObjectName("toolbar")
        header.setFixedHeight(48)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(12, 0, 12, 0)

        title = QLabel("🗺️  Peta GPS")
        title.setStyleSheet("font-size: 16px; font-weight: 700; color: #a78bfa;")
        hl.addWidget(title)

        hl.addStretch()
        self.btn_scan = QPushButton("📍 Pindai Manual (soon)")
        self.btn_scan.setEnabled(False)
        self.btn_scan.setToolTip("Fitur pemindaian area ini sedang dalam pengembangan")
        self.btn_scan.setCursor(Qt.CursorShape.ArrowCursor)
        self.btn_scan.clicked.connect(self._on_scan_clicked)
        hl.addWidget(self.btn_scan)

        layout.addWidget(header)

        # Filter Area
        self.filter_container = QFrame()
        self.filter_container.setStyleSheet("background: #0d0d1a; border-bottom: 1px solid #222235;")
        fl = QVBoxLayout(self.filter_container)
        fl.setContentsMargins(12, 8, 12, 8)
        fl.setSpacing(6)

        # Row 1: Countries
        self.scroll_countries = QScrollArea()
        self.scroll_countries.setWidgetResizable(True)
        self.scroll_countries.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_countries.setFixedHeight(30)
        self.country_widget = QWidget()
        self.country_layout = QHBoxLayout(self.country_widget)
        self.country_layout.setContentsMargins(0,0,0,0)
        self.scroll_countries.setWidget(self.country_widget)
        fl.addWidget(self.scroll_countries)

        # Row 2: Cities/Districts (Hidden initially)
        self.scroll_cities = QScrollArea()
        self.scroll_cities.setWidgetResizable(True)
        self.scroll_cities.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_cities.setFixedHeight(30)
        self.city_widget = QWidget()
        self.city_layout = QHBoxLayout(self.city_widget)
        self.city_layout.setContentsMargins(0,0,0,0)
        self.scroll_cities.setWidget(self.city_widget)
        self.scroll_cities.setVisible(False)
        fl.addWidget(self.scroll_cities)

        layout.addWidget(self.filter_container)

        # WebEngine View
        self.web_view = QWebEngineView()
        self.web_view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.web_view.loadFinished.connect(self._on_load_finished)
        
        # Setup Bridge
        self.bridge = MapBridge()
        self.bridge.photo_clicked.connect(self._open_lightbox)
        self.channel = QWebChannel()
        self.channel.registerObject("pythonBridge", self.bridge)
        self.web_view.page().setWebChannel(self.channel)

        # Aktifkan akses file lokal agar bisa menampilkan thumbnail langsung dari disk
        settings = self.web_view.settings()
        settings.setAttribute(settings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(settings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        
        layout.addWidget(self.web_view)
        
        # Load initial HTML
        self.web_view.setHtml(MAP_HTML)

    def _open_lightbox(self, photo_id):
        """Membuka Lightbox untuk foto tertentu yang diklik di peta."""
        # Cari index foto berdasarkan ID dalam list yang sedang ditampilkan
        idx = -1
        for i, p in enumerate(self._all_photos_gps):
            if p['id'] == photo_id:
                idx = i
                break
        
        if idx != -1:
            lb = Lightbox(self._all_photos_gps, idx, self, source="map")
            lb.exec()

    def _on_scan_clicked(self):
        # Minta JavaScript memberikan ID foto yang ada di area zoom saat ini
        self.web_view.page().runJavaScript("getVisibleIds();", self._emit_geocode_with_ids)

    def _emit_geocode_with_ids(self, ids):
        # Jika tidak ada yang terlihat, kirim list kosong (nanti diproses global atau diabaikan)
        self.geocode_requested.emit(ids if isinstance(ids, list) else [])

    def _on_load_finished(self, success):
        if success:
            self._is_loaded = True
            self.refresh_data(fit_bounds=True)

    def refresh_data(self, fit_bounds=False):
        """Ambil data terbaru dari database dan perbarui marker."""
        try:
            settings = QSettings("GalleryAIPro", "Gallery AI Pro")
            mode = settings.value("api/gps_mode", "Offline (Cepat, Privat)")
            col_prefix = "on" if "Online" in mode else "off"

            # OPTIMASI: Gunakan kueri tunggal yang menggabungkan foto dan thumbnail
            photos_raw = get_gps_photos_with_thumbs(col_prefix)
            self._all_photos_gps = []
            
            for p in photos_raw:
                # Mapping data dari kueri yang sudah di-JOIN
                photo_data = dict(p)
                photo_data['lat'] = p['gps_lat']
                photo_data['lng'] = p['gps_lng']
                photo_data['country'] = p.get(f'{col_prefix}_country') or "Unknown"
                photo_data['city'] = p.get(f'{col_prefix}_city') or "Unknown Area"
                
                # Generate URL file lokal yang valid menggunakan QUrl (Fix PR-4)
                thumb = p.get('thumb')
                actual_path = thumb if (thumb and thumb != "None" and thumb != "null") else p['path']
                photo_data['img_url'] = QUrl.fromLocalFile(actual_path).toString()
                
                self._all_photos_gps.append(photo_data)
            
            self._render_filters()
            self._apply_current_filters(fit_bounds=fit_bounds)
            
        except Exception as e:
            print(f"[MapPanel] Error refreshing data: {e}")

    def _render_filters(self):
        # Clear current layouts
        while self.country_layout.count():
            w = self.country_layout.takeAt(0).widget()
            if w: w.deleteLater()
        while self.city_layout.count():
            w = self.city_layout.takeAt(0).widget()
            if w: w.deleteLater()

        # Aggregasi data
        countries = {}
        for p in self._all_photos_gps:
            c = p['country']
            countries[c] = countries.get(c, 0) + 1

        # Render Baris 1: Negara
        btn_all = FilterChip("Semua Lokasi")
        btn_all.setChecked(self._selected_country is None)
        btn_all.clicked.connect(lambda: self._set_country(None))
        self.country_layout.addWidget(btn_all)

        for name, count in sorted(countries.items()):
            chip = FilterChip(name, count)
            chip.setChecked(self._selected_country == name)
            chip.clicked.connect(lambda checked, n=name: self._set_country(n))
            self.country_layout.addWidget(chip)
        self.country_layout.addStretch()

        # Render Baris 2: Kota (Hanya jika negara dipilih)
        if self._selected_country:
            cities = {}
            for p in self._all_photos_gps:
                if p['country'] == self._selected_country:
                    city = p['city']
                    cities[city] = cities.get(city, 0) + 1
            
            if cities:
                self.scroll_cities.setVisible(True)
                btn_all_city = FilterChip(f"Semua di {self._selected_country}")
                btn_all_city.setChecked(self._selected_city is None)
                btn_all_city.clicked.connect(lambda: self._set_city(None))
                self.city_layout.addWidget(btn_all_city)

                for name, count in sorted(cities.items()):
                    chip = FilterChip(name, count)
                    chip.setChecked(self._selected_city == name)
                    chip.clicked.connect(lambda checked, n=name: self._set_city(n))
                    self.city_layout.addWidget(chip)
                self.city_layout.addStretch()
            else:
                self.scroll_cities.setVisible(False)
        else:
            self.scroll_cities.setVisible(False)

    def _set_country(self, country, fit_bounds=True):
        self._selected_country = country
        self._selected_city = None # Reset city when country changes
        self._render_filters()
        self._apply_current_filters(fit_bounds=fit_bounds)

    def _set_city(self, city, fit_bounds=True):
        self._selected_city = city
        self._render_filters()
        self._apply_current_filters(fit_bounds=fit_bounds)

    def _apply_current_filters(self, fit_bounds=False):
        filtered_data = []
        for p in self._all_photos_gps:
            match_country = (self._selected_country is None or p['country'] == self._selected_country)
            match_city = (self._selected_city is None or p['city'] == self._selected_city)
            
            if match_country and match_city:
                filtered_data.append(p)
        
        if self._is_loaded:
            self._apply_markers(filtered_data, fit_bounds=fit_bounds)

    def _apply_markers(self, data, fit_bounds=False):
        json_data = json.dumps(data)
        fit_js = "true" if fit_bounds else "false"
        # Inject JavaScript ke dalam WebEngine
        self.web_view.page().runJavaScript(f"updateMarkers({json_data}, {fit_js});")

    def showEvent(self, event):
        super().showEvent(event)
        # Berikan sedikit jeda tambahan agar layout stabil sebelum menghitung bounds peta
        QTimer.singleShot(300, lambda: self.refresh_data(fit_bounds=True))