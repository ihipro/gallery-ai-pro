try:
    import reverse_geocoder as rg
    HAS_RG = True
except ImportError:
    HAS_RG = False

try:
    from geopy.geocoders import Nominatim
    HAS_GEOPY = True
except ImportError:
    HAS_GEOPY = False

from PySide6.QtCore import QSettings
import time

# Kamus sederhana untuk mengubah kode ISO Negara menjadi nama lengkap (Offline Mode) 
COUNTRY_MAP = {
    'ID': 'Indonesia', 'JP': 'Jepang', 'US': 'USA', 'SG': 'Singapura',
    'MY': 'Malaysia', 'TH': 'Thailand', 'KR': 'Korea Selatan', 'CN': 'Tiongkok'
}

def reverse_geocode(lat, lng, geolocator=None):
    """Fungsi utama untuk mendapatkan alamat berdasarkan koordinat."""
    settings = QSettings("GalleryAIPro", "Gallery AI Pro")
    mode = settings.value("api/gps_mode", "Offline (Cepat, Privat)")
    
    try:
        if "Online" in mode and HAS_GEOPY:
            # Mode Online: Geopy (Nominatim)
            # Re-use geolocator instance for better performance and policy compliance
            if geolocator is None:
                geolocator = Nominatim(user_agent="GalleryAIPro_v4")
            
            location = geolocator.reverse((lat, lng), timeout=10)
            if location and 'address' in location.raw:
                addr = location.raw['address']
                
                # Fallback Chain untuk Kota di Indonesia (Kecamatan/Kota/Kabupaten)
                city = (addr.get("city") or addr.get("town") or 
                        addr.get("municipality") or addr.get("county") or "Unknown City")
                
                # Fallback Chain untuk Distrik/Kelurahan
                district = (addr.get("suburb") or addr.get("village") or 
                            addr.get("city_district") or addr.get("neighbourhood") or "")

                return {
                    "country": addr.get("country", "Unknown"),
                    "city": city,
                    "district": district
                }
        elif HAS_RG:
            # Mode Offline: reverse_geocoder
            # rg.search menerima tuple (lat, lng)
            results = rg.search((lat, lng), verbose=False)
            if results:
                res = results[0]
                iso_code = res.get('cc', '')
                country_name = COUNTRY_MAP.get(iso_code, iso_code)
                
                # Perbaikan Mapping Indonesia:
                # admin2 biasanya berisi Kota/Kabupaten (Surabaya, Bangkalan)
                # name biasanya berisi lokasi lebih spesifik (Kecamatan/Desa)
                city = res.get('admin2') or res.get('name') or "Unknown City"
                district = res.get('name') if res.get('admin2') else ""

                return {
                    "country": country_name,
                    "city": city,
                    "district": district
                }
        else:
            print("[Geocoder] Error: Required geocoding library is not installed.")
    except Exception as e:
        # Jika error 429 (Online), lemparkan ke atas agar Worker bisa berhenti
        if "429" in str(e) or "Too Many Requests" in str(e):
            raise e
        print(f"[Geocoder] Error: {e}")
    
    return { "country": "Unknown", "city": "Unknown", "district": "" }

def get_delay_needed():
    """Cek apakah butuh delay (hanya mode Online Nominatim yang butuh)."""
    settings = QSettings("GalleryAIPro", "Gallery AI Pro")
    mode = settings.value("api/gps_mode", "Offline")
    return 1.2 if "Online" in mode else 0.0