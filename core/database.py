"""
core/database.py
Manages all persistent data via SQLite.
"""

import sqlite3
import json
import os
from datetime import datetime
from contextlib import contextmanager
from pathlib import Path


DB_PATH = Path(__file__).parent.parent / "data" / "gallery.db"


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # better concurrent read perf
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

@contextmanager
def db_session():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    """Create tables if they don't exist."""
    with db_session() as conn:
        cur = conn.cursor()
        cur.executescript("""
        CREATE TABLE IF NOT EXISTS photos (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            path        TEXT    UNIQUE NOT NULL,
            uid         TEXT    UNIQUE,
            name        TEXT    NOT NULL,
            folder      TEXT    NOT NULL,
            file_size   INTEGER DEFAULT 0,
            modified_at REAL    DEFAULT 0,
            img_w       INTEGER DEFAULT 0,
            img_h       INTEGER DEFAULT 0,
            date_taken  TEXT,
            camera      TEXT,
            gps_lat     REAL,
            gps_lng     REAL,
            address_country  TEXT,
            address_city     TEXT,
            address_district TEXT,
            off_country      TEXT,
            off_city         TEXT,
            off_district     TEXT,
            on_country       TEXT,
            on_city          TEXT,
            on_district      TEXT,
            added_at    TEXT    NOT NULL,
            tagged      INTEGER DEFAULT 0,
            ai_tagged   INTEGER DEFAULT 0,
            fav         INTEGER DEFAULT 0,
            note        TEXT    DEFAULT '',
            tags        TEXT    DEFAULT '{}',
            face_names  TEXT    DEFAULT '[]',
            face_recognized INTEGER DEFAULT 0,
            exif_data   TEXT    DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS thumb_cache (
            photo_path  TEXT PRIMARY KEY,
            thumb_path  TEXT NOT NULL,
            created_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS face_db (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT UNIQUE NOT NULL,
            descriptors TEXT DEFAULT '[]',
            ref_thumbs  TEXT DEFAULT '[]',
            created_at  TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_photos_folder   ON photos(folder);
        CREATE INDEX IF NOT EXISTS idx_photos_tagged   ON photos(tagged);
        CREATE INDEX IF NOT EXISTS idx_photos_ai       ON photos(ai_tagged);
        CREATE INDEX IF NOT EXISTS idx_photos_fav      ON photos(fav);
        CREATE INDEX IF NOT EXISTS idx_photos_added    ON photos(added_at);
    """)

        cols = {row["name"] for row in cur.execute("PRAGMA table_info(photos)").fetchall()}
        if "modified_at" not in cols:
            cur.execute("ALTER TABLE photos ADD COLUMN modified_at REAL DEFAULT 0")
        if "uid" not in cols:
            cur.execute("ALTER TABLE photos ADD COLUMN uid TEXT")
        if "face_recognized" not in cols:
            cur.execute("ALTER TABLE photos ADD COLUMN face_recognized INTEGER DEFAULT 0")
        
        # Add Dual-Track columns if missing
        new_cols = [
            "off_country", "off_city", "off_district",
            "on_country", "on_city", "on_district"
        ]
        for col in new_cols:
            if col not in cols:
                cur.execute(f"ALTER TABLE photos ADD COLUMN {col} TEXT")

        conn.commit()


# ── Photo CRUD ───────────────────────────────────

def upsert_photo(photo: dict) -> int:
    """Insert or update a photo record. Returns photo id."""
    with db_session() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO photos
                (path, uid, name, folder, file_size, modified_at, img_w, img_h,
                 date_taken, camera, gps_lat, gps_lng, address_country, address_city, address_district,
                 off_country, off_city, off_district, on_country, on_city, on_district,
                 added_at, tagged, ai_tagged, fav, note, tags, face_names, face_recognized, exif_data)
            VALUES
                (:path, :uid, :name, :folder, :file_size, :modified_at, :img_w, :img_h,
                 :date_taken, :camera, :gps_lat, :gps_lng, 
                 :address_country, :address_city, :address_district,
                 :off_country, :off_city, :off_district, :on_country, :on_city, :on_district,
                 :added_at, :tagged, :ai_tagged, :fav, :note, :tags, :face_names, :face_recognized, :exif_data)
            ON CONFLICT(path) DO UPDATE SET
                uid        = excluded.uid,
                name       = excluded.name,
                file_size  = excluded.file_size,
                modified_at = excluded.modified_at,
                img_w      = excluded.img_w,
                img_h      = excluded.img_h,
                date_taken = excluded.date_taken,
                camera     = excluded.camera,
                gps_lat    = excluded.gps_lat,
                gps_lng    = excluded.gps_lng,
                address_country = excluded.address_country,
                address_city    = excluded.address_city,
                address_district = excluded.address_district,
                off_country     = excluded.off_country,
                off_city        = excluded.off_city,
                off_district    = excluded.off_district,
                on_country      = excluded.on_country,
                on_city         = excluded.on_city,
                on_district     = excluded.on_district,
                tagged     = excluded.tagged,
                ai_tagged  = excluded.ai_tagged,
                fav        = excluded.fav,
                note       = excluded.note,
                tags       = excluded.tags,
                face_names = excluded.face_names,
                face_recognized = excluded.face_recognized,
                exif_data  = excluded.exif_data
        """, {
            'path':       photo['path'],
            'uid':        photo.get('uid'),
            'name':       photo.get('name', os.path.basename(photo['path'])),
            'folder':     str(Path(photo['path']).parent),
            'file_size':  photo.get('file_size', 0),
            'modified_at': photo.get('modified_at', 0),
            'img_w':      photo.get('img_w', 0),
            'img_h':      photo.get('img_h', 0),
            'date_taken': photo.get('date_taken'),
            'camera':     photo.get('camera'),
            'gps_lat':    photo.get('gps_lat'),
            'gps_lng':    photo.get('gps_lng'),
            'address_country': photo.get('address_country'),
            'address_city':    photo.get('address_city'),
            'address_district': photo.get('address_district'),
            'off_country':     photo.get('off_country'),
            'off_city':        photo.get('off_city'),
            'off_district':    photo.get('off_district'),
            'on_country':      photo.get('on_country'),
            'on_city':         photo.get('on_city'),
            'on_district':     photo.get('on_district'),
            'added_at':   photo.get('added_at', datetime.now().isoformat()),
            'tagged':     int(photo.get('tagged', False)),
            'ai_tagged':  int(photo.get('ai_tagged', False)),
            'fav':        int(photo.get('fav', False)),
            'note':       photo.get('note', ''),
            'tags':       json.dumps(photo.get('tags', {})),
            'face_names': json.dumps(photo.get('face_names', [])),
            'face_recognized': int(photo.get('face_recognized', False)),
            'exif_data':  json.dumps(photo.get('exif_data', {})),
        })
        photo_id = cur.lastrowid
        conn.commit()
        return photo_id

def upsert_photos_batch(photos: list[dict]):
    """
    Memasukkan banyak foto sekaligus dalam satu transaksi.
    Sangat jauh lebih cepat untuk folder berisi ribuan file.
    """
    if not photos:
        return

    query = """
        INSERT INTO photos
            (path, uid, name, folder, file_size, modified_at, img_w, img_h,
             date_taken, camera, gps_lat, gps_lng, address_country, address_city, address_district,
             off_country, off_city, off_district, on_country, on_city, on_district,
             added_at, tagged, ai_tagged, fav, note, tags, face_names, face_recognized, exif_data)
        VALUES
            (:path, :uid, :name, :folder, :file_size, :modified_at, :img_w, :img_h,
             :date_taken, :camera, :gps_lat, :gps_lng, 
             :address_country, :address_city, :address_district,
             :off_country, :off_city, :off_district, :on_country, :on_city, :on_district,
             :added_at, :tagged, :ai_tagged, :fav, :note, :tags, :face_names, :face_recognized, :exif_data)
        ON CONFLICT(path) DO UPDATE SET
            file_size   = excluded.file_size,
            modified_at = excluded.modified_at,
            img_w       = excluded.img_w,
            img_h       = excluded.img_h,
            date_taken  = excluded.date_taken,
            camera      = excluded.camera,
            gps_lat     = excluded.gps_lat,
            gps_lng     = excluded.gps_lng,
            exif_data   = excluded.exif_data
    """
    
    with db_session() as conn:
        cur = conn.cursor()
        data_list = []
        now = datetime.now().isoformat()
        
        for p in photos:
            # Pastikan SEMUA kunci yang dibutuhkan kueri SQL ada, berikan default jika kosong
            d = {
                'path':             p['path'],
                'uid':              p.get('uid'),
                'name':             p.get('name', os.path.basename(p['path'])),
                'folder':           p.get('folder', str(Path(p['path']).parent)),
                'file_size':        int(p.get('file_size', 0)),
                'modified_at':      float(p.get('modified_at', 0)),
                'img_w':            int(p.get('img_w', 0)),
                'img_h':            int(p.get('img_h', 0)),
                'date_taken':       p.get('date_taken'),
                'camera':           p.get('camera'),
                'gps_lat':          p.get('gps_lat'),
                'gps_lng':          p.get('gps_lng'),
                'address_country':  p.get('address_country'),
                'address_city':     p.get('address_city'),
                'address_district': p.get('address_district'),
                'off_country':      p.get('off_country'),
                'off_city':         p.get('off_city'),
                'off_district':     p.get('off_district'),
                'on_country':       p.get('on_country'),
                'on_city':          p.get('on_city'),
                'on_district':      p.get('on_district'),
                'added_at':         p.get('added_at', now),
                'tagged':           int(p.get('tagged', 0)),
                'ai_tagged':        int(p.get('ai_tagged', 0)),
                'fav':              int(p.get('fav', 0)),
                'note':             p.get('note', ''),
                'tags':             json.dumps(p.get('tags', {})),
                'face_names':       json.dumps(p.get('face_names', [])),
                'face_recognized':  int(p.get('face_recognized', 0)),
                'exif_data':        json.dumps(p.get('exif_data', {}))
            }
            data_list.append(d)
            
        cur.executemany(query, data_list)
        conn.commit()

def normalize_tags(res: dict) -> dict:
    """
    Python implementation of web version's applyResFields().
    Ensures that empty strings or 'null' strings are stored as None.
    """
    fields = [
        'bg', 'ruang', 'detail_alam', 'waktu', 'konten', 'tipe_foto', 
        'pose', 'mood', 'outfit', 'expr', 'kacamata', 'rambut', 
        'postur', 'aksesori', 'usia', 'wilayah', 'destinasi', 
        'aktivitas', 'doc_type', 'bahasa_teks', 'relasi', 'sudut'
    ]
    
    normalized = {}
    for f in fields:
        val = res.get(f)
        if val in (None, '', 'null', 'None'):
            normalized[f] = None
        else:
            normalized[f] = val
    return normalized


def get_photos_in_folder(folder: str) -> list[dict]:
    """Get photos directly in folder (non-recursive — matches scan behaviour)."""
    with db_session() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM photos
            WHERE folder = ?
            ORDER BY added_at DESC
        """, (folder,))
        rows = cur.fetchall()
        return [_row_to_dict(r) for r in rows]


def get_gps_photos_with_thumbs(col_prefix: str) -> list[dict]:
    """Optimized query: Ambil semua data GPS dan Thumb dalam satu kali join."""
    with db_session() as conn:
        cur = conn.cursor()
        query = f"""
            SELECT p.*, t.thumb_path as thumb 
            FROM photos p
            LEFT JOIN thumb_cache t ON p.path = t.photo_path
            WHERE p.gps_lat IS NOT NULL AND p.gps_lng IS NOT NULL
        """
        cur.execute(query)
        rows = cur.fetchall()
        return [_row_to_dict(r) for r in rows]


def get_all_photos() -> list[dict]:
    with db_session() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM photos ORDER BY added_at DESC")
        rows = cur.fetchall()
        return [_row_to_dict(r) for r in rows]


def update_tags(path: str, tags: dict, note: str = '',
                tagged: bool = True, ai_tagged: bool = False):
    with db_session() as conn:
        conn.execute("""
            UPDATE photos
            SET tags=?, note=?, tagged=?, ai_tagged=?
            WHERE path=?
        """, (json.dumps(tags), note, int(tagged), int(ai_tagged), path))
        conn.commit()


def toggle_fav(path: str) -> bool:
    """Toggle favorite, returns new state."""
    with db_session() as conn:
        cur = conn.cursor()
        cur.execute("SELECT fav FROM photos WHERE path=?", (path,))
        row = cur.fetchone()
        if not row:
            return False
        new_fav = not bool(row['fav'])
        conn.execute("UPDATE photos SET fav=? WHERE path=?", (int(new_fav), path))
        conn.commit()
        return new_fav


def delete_photo(path: str):
    with db_session() as conn:
        conn.execute("DELETE FROM photos WHERE path=?", (path,))
        conn.commit()


def get_stats() -> dict:
    with db_session() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                COUNT(*) as total,
                SUM(tagged)   as tagged,
                SUM(ai_tagged) as ai_tagged,
                SUM(fav)      as fav
            FROM photos
        """)
        row = cur.fetchone()
        return dict(row) if row else {'total': 0, 'tagged': 0, 'ai_tagged': 0, 'fav': 0}

def get_photos_needing_geocode(mode: str, photo_ids: list = None) -> list[dict]:
    """Ambil foto yang punya koordinat tapi belum punya data alamat untuk mode spesifik."""
    with db_session() as conn:
        cur = conn.cursor()
        
        # Dual-Track Logic: Cek kolom yang sesuai dengan mode aktif
        col_prefix = "on" if "Online" in mode else "off"
        
        id_filter = ""
        limit = 100
        
        # Jika photo_ids diberikan (Spatial Geocoding), batasi hanya pada ID tersebut
        if photo_ids is not None:
            if not photo_ids:
                return []  # Jika list kosong, jangan cari apa pun

            # Pastikan semua ID adalah integer murni
            photo_ids = [i for i in photo_ids if i is not None]
            
            try:
                clean_ids = list(set([int(float(i)) for i in photo_ids if i is not None]))
            except (ValueError, TypeError):
                return []
                
            if not clean_ids: return []
            id_list = ",".join(map(str, clean_ids))
            id_filter = f"AND id IN ({id_list})"
            limit = 500    # Batas lebih besar untuk pindaian manual area zoom

        query = f"""
            SELECT id, path, gps_lat, gps_lng FROM photos
            WHERE gps_lat IS NOT NULL AND gps_lng IS NOT NULL
            AND (
                {col_prefix}_country IS NULL 
                OR {col_prefix}_country = '' 
                OR {col_prefix}_country IN ('Unknown', 'Unknown Area', 'null', 'None')
            )
            {id_filter}
            LIMIT {limit}
        """
        cur.execute(query)
        rows = cur.fetchall()
        return [dict(r) for r in rows]

def update_photo_address(photo_id: int, country: str, city: str, district: str, mode: str):
    """Update data alamat hasil geocoding ke kolom yang sesuai (Dual-Track)."""
    with db_session() as conn:
        col_prefix = "on" if "Online" in mode else "off"
        
        # Kita tetap update kolom address_ umum untuk backward compatibility filter UI lama jika perlu
        query = f"""
            UPDATE photos
            SET address_country=?, address_city=?, address_district=?,
                {col_prefix}_country=?, {col_prefix}_city=?, {col_prefix}_district=?
            WHERE id=?
        """
        conn.execute(query, (country, city, district, country, city, district, photo_id))
        conn.commit()

def reset_photo_addresses(mode: str):
    """Menghapus data alamat (offline atau online) agar bisa di-geocode ulang."""
    with db_session() as conn:
        col_prefix = "on" if "Online" in mode else "off"
        # Reset kolom umum dan kolom spesifik track (Dual-Track)
        query = f"""
            UPDATE photos 
            SET address_country=NULL, address_city=NULL, address_district=NULL,
                {col_prefix}_country=NULL, {col_prefix}_city=NULL, {col_prefix}_district=NULL
        """
        conn.execute(query)
        conn.commit()


# ── Thumb cache ──────────────────────────────────

def get_thumb_path(photo_path: str) -> str | None:
    with db_session() as conn:
        cur = conn.cursor()
        cur.execute("SELECT thumb_path FROM thumb_cache WHERE photo_path=?", (photo_path,))
        row = cur.fetchone()
        if row:
            tp = row['thumb_path']
            return tp if os.path.exists(tp) else None
        return None


def save_thumb_path(photo_path: str, thumb_path: str):
    with db_session() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO thumb_cache (photo_path, thumb_path, created_at)
            VALUES (?, ?, ?)
        """, (photo_path, thumb_path, datetime.now().isoformat()))
        conn.commit()


# ── Helpers ──────────────────────────────────────

def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d['tags']       = json.loads(d.get('tags') or '{}')
    d['face_names'] = json.loads(d.get('face_names') or '[]')
    d['exif_data']  = json.loads(d.get('exif_data') or '{}')
    d['tagged']     = bool(d.get('tagged'))
    d['ai_tagged']  = bool(d.get('ai_tagged'))
    d['fav']        = bool(d.get('fav'))
    d['modified_at'] = float(d.get('modified_at') or 0)
    d['face_recognized'] = bool(d.get('face_recognized', 0))
    return d
