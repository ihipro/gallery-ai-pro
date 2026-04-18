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
    conn = get_connection()
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

    conn.commit()
    conn.close()


# ── Photo CRUD ───────────────────────────────────

def upsert_photo(photo: dict) -> int:
    """Insert or update a photo record. Returns photo id."""
    with db_session() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO photos
                (path, uid, name, folder, file_size, modified_at, img_w, img_h,
                 date_taken, camera, gps_lat, gps_lng,
                 added_at, tagged, ai_tagged, fav, note, tags, face_names, face_recognized, exif_data)
            VALUES
                (:path, :uid, :name, :folder, :file_size, :modified_at, :img_w, :img_h,
                 :date_taken, :camera, :gps_lat, :gps_lng,
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
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM photos
        WHERE folder = ?
        ORDER BY added_at DESC
    """, (folder,))
    rows = cur.fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def get_all_photos() -> list[dict]:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM photos ORDER BY added_at DESC")
    rows = cur.fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def update_tags(path: str, tags: dict, note: str = '',
                tagged: bool = True, ai_tagged: bool = False):
    conn = get_connection()
    conn.execute("""
        UPDATE photos
        SET tags=?, note=?, tagged=?, ai_tagged=?
        WHERE path=?
    """, (json.dumps(tags), note, int(tagged), int(ai_tagged), path))
    conn.commit()
    conn.close()


def toggle_fav(path: str) -> bool:
    """Toggle favorite, returns new state."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT fav FROM photos WHERE path=?", (path,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return False
    new_fav = not bool(row['fav'])
    conn.execute("UPDATE photos SET fav=? WHERE path=?", (int(new_fav), path))
    conn.commit()
    conn.close()
    return new_fav


def delete_photo(path: str):
    conn = get_connection()
    conn.execute("DELETE FROM photos WHERE path=?", (path,))
    conn.commit()
    conn.close()


def get_stats() -> dict:
    conn = get_connection()
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
    conn.close()
    return dict(row) if row else {'total': 0, 'tagged': 0, 'ai_tagged': 0, 'fav': 0}


# ── Thumb cache ──────────────────────────────────

def get_thumb_path(photo_path: str) -> str | None:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT thumb_path FROM thumb_cache WHERE photo_path=?", (photo_path,))
    row = cur.fetchone()
    conn.close()
    if row:
        tp = row['thumb_path']
        return tp if os.path.exists(tp) else None
    return None


def save_thumb_path(photo_path: str, thumb_path: str):
    conn = get_connection()
    conn.execute("""
        INSERT OR REPLACE INTO thumb_cache (photo_path, thumb_path, created_at)
        VALUES (?, ?, ?)
    """, (photo_path, thumb_path, datetime.now().isoformat()))
    conn.commit()
    conn.close()


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
