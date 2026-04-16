"""
core/thumbnailer.py

Fixes:
  - GPS IFDRational/Fraction values now converted to float before DB insert
  - All numeric EXIF values (aperture, shutter, focal) similarly coerced
  - FolderScanWorker.run() wraps everything in try/except so finished
    signal always fires even if individual photo read errors occur
  - Thumbnail generation stays async (not called inside scan loop)
"""

import os
import hashlib
from pathlib import Path
from PIL import Image, ImageOps

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from core.database import get_thumb_path, save_thumb_path


THUMB_DIR  = Path(__file__).parent.parent / "data" / "thumbs"
THUMB_SIZE = (320, 320)
AI_SIZE    = (1500, 1500)


def get_or_create_thumb(photo_path: str) -> str | None:
    cached = get_thumb_path(photo_path)
    if cached:
        return cached
    return _generate_thumb(photo_path)


def _thumb_filename(photo_path: str) -> str:
    return hashlib.md5(photo_path.encode()).hexdigest() + ".jpg"


def _generate_thumb(photo_path: str) -> str | None:
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    thumb_path = str(THUMB_DIR / _thumb_filename(photo_path))
    try:
        with Image.open(photo_path) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode not in ('RGB', 'L'):
                img = img.convert('RGB')
            img.thumbnail(THUMB_SIZE, Image.Resampling.LANCZOS)
            img.save(thumb_path, 'JPEG', quality=82, optimize=True)
        save_thumb_path(photo_path, thumb_path)
        return thumb_path
    except Exception as e:
        print(f"[Thumbnailer] Error for {photo_path}: {e}")
        return None


def generate_ai_blob(photo_path: str) -> str | None:
    ai_dir = Path(__file__).parent.parent / "data" / "ai_blobs"
    ai_dir.mkdir(parents=True, exist_ok=True)
    out_path = str(ai_dir / _thumb_filename(photo_path))
    if os.path.exists(out_path):
        return out_path
    try:
        with Image.open(photo_path) as img:
            img = ImageOps.exif_transpose(img)
            if img.mode not in ('RGB', 'L'):
                img = img.convert('RGB')
            img.thumbnail(AI_SIZE, Image.Resampling.LANCZOS)
            img.save(out_path, 'JPEG', quality=88, optimize=True)
        return out_path
    except Exception as e:
        print(f"[Thumbnailer] AI blob error for {photo_path}: {e}")
        return None


# ── Helpers ───────────────────────────────────────

def _to_float(val) -> float | None:
    """Safely convert any numeric / Fraction / IFDRational to Python float."""
    if val is None:
        return None
    try:
        return float(val)
    except Exception:
        return None


def _to_int(val) -> int | None:
    try:
        return int(val)
    except Exception:
        return None


# ── Async thumbnail loading ──────────────────────

class ThumbSignals(QObject):
    done  = Signal(str, str)
    error = Signal(str)


class ThumbWorker(QRunnable):
    def __init__(self, photo_path: str, signals: ThumbSignals):
        super().__init__()
        self.photo_path = photo_path
        self.signals = signals
        self.setAutoDelete(True)

    def run(self):
        thumb = get_or_create_thumb(self.photo_path)
        try:
            if thumb:
                self.signals.done.emit(self.photo_path, thumb)
            else:
                self.signals.error.emit(self.photo_path)
        except RuntimeError:
            pass  # signals QObject was deleted before emit — safe to ignore


class ThumbLoader(QObject):
    thumb_ready = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pool = QThreadPool.globalInstance()
        self.pool.setMaxThreadCount(4)
        self._pending: set[str] = set()
        # Keep a strong Python ref to each ThumbSignals until the worker finishes.
        # Without this, Python GC may delete the QObject while the thread is still
        # running → RuntimeError: Signal source has been deleted.
        self._active_signals: dict[str, ThumbSignals] = {}

    def request(self, photo_path: str):
        if photo_path in self._pending:
            return
        self._pending.add(photo_path)
        signals = ThumbSignals()
        signals.done.connect(self._on_done)
        signals.error.connect(self._on_error)
        self._active_signals[photo_path] = signals   # ← keep alive
        self.pool.start(ThumbWorker(photo_path, signals))

    def _on_done(self, photo_path: str, thumb_path: str):
        self._pending.discard(photo_path)
        self._active_signals.pop(photo_path, None)   # ← release ref
        self.thumb_ready.emit(photo_path, thumb_path)

    def _on_error(self, photo_path: str):
        self._pending.discard(photo_path)
        self._active_signals.pop(photo_path, None)   # ← release ref


# ── Batch scanner ────────────────────────────────

class ScannerSignals(QObject):
    progress    = Signal(int, int)
    photo_found = Signal(dict)
    finished    = Signal(int)
    error       = Signal(str)


class FolderScanWorker(QRunnable):
    IMAGE_EXT = {'.jpg','.jpeg','.png','.webp','.gif','.bmp','.tiff','.tif','.heic'}

    def __init__(self, folder: str, signals: ScannerSignals):
        super().__init__()
        self.folder = folder
        self.signals = signals
        self.setAutoDelete(True)
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        """
        Scan ONLY direct files in self.folder — NOT recursive.
        Subfolders are shown as navigable cards; user double-clicks into them.
        finished() always emits so the UI progress bar always clears.
        """
        from core.database import get_photos_in_folder, upsert_photo
        done = 0
        try:
            all_entries = []
            try:
                for entry in os.scandir(self.folder):
                    if (entry.is_file(follow_symlinks=False)
                            and os.path.splitext(entry.name)[1].lower() in self.IMAGE_EXT):
                        all_entries.append(entry)
            except PermissionError:
                pass
            all_entries.sort(key=lambda entry: entry.path)

            total = len(all_entries)
            existing_by_path = {
                photo["path"]: photo
                for photo in get_photos_in_folder(self.folder)
            }

            for entry in all_entries:
                if self._cancelled:
                    break
                path = entry.path
                try:
                    stat = entry.stat(follow_symlinks=False)
                    existing = existing_by_path.get(path)
                    if (existing
                            and int(existing.get("file_size", 0)) == int(stat.st_size)
                            and abs(float(existing.get("modified_at", 0)) - float(stat.st_mtime)) < 0.001):
                        meta = existing
                    else:
                        meta = self._read_meta(path, stat)
                        upsert_photo(meta)
                    # Thumbnail generation is intentionally NOT called here.
                    # ThumbLoader handles it async when cards are displayed.
                    done += 1
                    try:
                        self.signals.progress.emit(done, total)
                        self.signals.photo_found.emit(meta)
                    except RuntimeError:
                        return  # signals deleted → panel was replaced, stop quietly
                except Exception as e:
                    print(f"[Scanner] Skipping {path}: {e}")
                    done += 1
                    try:
                        self.signals.progress.emit(done, total)
                    except RuntimeError:
                        return

        except Exception as e:
            print(f"[Scanner] Fatal error: {e}")
            try: self.signals.error.emit(str(e))
            except RuntimeError: pass
        finally:
            # Always emit finished so the progress bar clears
            try:
                self.signals.finished.emit(done)
            except RuntimeError:
                pass  # signals GC'd — UI already moved on, that's fine

    def _read_meta(self, path: str, stat=None) -> dict:
        from datetime import datetime
        if stat is None:
            stat = os.stat(path)

        meta = {
            'path':      path,
            'name':      os.path.basename(path),
            'folder':    str(Path(path).parent),
            'file_size': stat.st_size,
            'modified_at': stat.st_mtime,
            'added_at':  datetime.now().isoformat(),
            'tags':      {},
            'exif_data': {},
        }

        try:
            with Image.open(path) as img:
                meta['img_w'], meta['img_h'] = img.size

                exif_raw = img._getexif() if hasattr(img, '_getexif') else None
                if exif_raw:
                    # Date taken
                    dt_tag = exif_raw.get(36867) or exif_raw.get(306)
                    if dt_tag:
                        try:
                            meta['date_taken'] = datetime.strptime(
                                str(dt_tag), "%Y:%m:%d %H:%M:%S").isoformat()
                        except Exception:
                            pass

                    # Camera make/model
                    make  = exif_raw.get(271) or b''
                    model = exif_raw.get(272) or b''
                    if isinstance(make,  bytes): make  = make.decode('utf-8', 'ignore')
                    if isinstance(model, bytes): model = model.decode('utf-8', 'ignore')
                    make = make.strip(); model = model.strip()
                    if make or model:
                        meta['camera'] = f"{make} {model}".strip()

                    # GPS — FIX: convert IFDRational/Fraction to plain float
                    gps_info = exif_raw.get(34853)
                    if gps_info:
                        lat = self._gps_to_decimal(gps_info.get(2), gps_info.get(1))
                        lng = self._gps_to_decimal(gps_info.get(4), gps_info.get(3))
                        if lat is not None:
                            meta['gps_lat'] = lat   # already float from _gps_to_decimal
                            meta['gps_lng'] = lng

                    # Extra EXIF — FIX: always coerce to native Python types
                    exif_d = {}
                    ap = _to_float(exif_raw.get(33437))
                    if ap is not None:
                        exif_d['aperture'] = f"f/{ap:.1f}"

                    et = _to_float(exif_raw.get(33434))
                    if et is not None:
                        exif_d['shutter'] = f"1/{round(1/et)}s" if et < 1 else f"{et}s"

                    iso = _to_int(exif_raw.get(34855))
                    if iso is not None:
                        exif_d['iso'] = f"ISO {iso}"

                    fl = _to_float(exif_raw.get(37386))
                    if fl is not None:
                        exif_d['focal'] = f"{fl:.0f}mm"

                    meta['exif_data'] = exif_d

        except Exception as e:
            print(f"[Scanner] EXIF read error {path}: {e}")

        return meta

    @staticmethod
    def _gps_to_decimal(dms, ref) -> float | None:
        """Convert GPS DMS tuple (may contain IFDRational/Fraction) to decimal float."""
        try:
            # Each of d, m, s may be IFDRational or Fraction — coerce to float
            d = float(dms[0])
            m = float(dms[1])
            s = float(dms[2])
            val = d + m / 60.0 + s / 3600.0
            if ref in (b'S', b'W', 'S', 'W'):
                val = -val
            return round(val, 6)
        except Exception:
            return None
