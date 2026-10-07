"""No shell invocation; decoders read pinned file descriptors, never source paths."""
from server_settings import get as host_setting
import contextlib
import json
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import sys

ROOT = Path(host_setting('fotolabor_root'))
HISTORY = 'converted from image/jpeg to image/dng'
RAW = {'.dng', '.raw', '.cr2', '.cr3', '.crw', '.nef', '.nrw', '.arw', '.srf', '.sr2',
       '.orf', '.rw2', '.raf', '.pef', '.srw', '.rwl', '.3fr', '.fff', '.iiq', '.kdc', '.dcr', '.mos', '.mrw', '.x3f'}
IMAGES = RAW | {'.jpg', '.jpeg', '.png', '.tif', '.tiff', '.heic', '.heif', '.webp', '.gif', '.bmp', '.avif', '.jxl'}
TOOLS = {'jpeginfo': 'jpeginfo', 'pngcheck': 'pngcheck', 'tiffinfo': 'libtiff-tools',
         'exiftool': 'libimage-exiftool-perl', 'dcraw_emu': 'libraw-bin', 'webpinfo': 'webp', 'heif-convert': 'libheif-examples'}

REASONS = {'missing_decoder': 'Prüfwerkzeug fehlt', 'unsupported_format': 'Format nicht unterstützt',
           'timeout': 'Zeitlimit überschritten', 'access': 'Datei nicht erreichbar / lesbar',
           'symlink': 'Symlink / Spezialdatei', 'changed': 'Während der Prüfung verändert',
           'metadata_warning': 'Metadaten nicht sicher lesbar', 'decoder_warning': 'Decoderwarnung / Variante nicht unterstützt',
           'resource_limit': 'Speicher- oder Größenlimit', 'unknown': 'Sonstiger Prüfgrund', 'damaged': 'Bilddaten defekt'}


def reason_code(reason, status='uncheckable'):
    if status == 'damaged':
        return 'damaged'
    if status != 'uncheckable':
        return ''
    text = reason.lower()
    for words, code in [(('symlink', 'keine reguläre'), 'symlink'),
                        (('fehlt (debian', 'missing_decoder'), 'missing_decoder'),
                        (('kein vollständiger decoder', 'nicht unterstützt'), 'unsupported_format'),
                        (('zeitlimit',), 'timeout'), (('permission denied', 'no such file', 'zugriff'), 'access'),
                        (('verändert',), 'changed'), (('exiftool',), 'metadata_warning'),
                        (('libraw', 'warnung'), 'decoder_warning')]:
        if any(word in text for word in words):
            return code
    return 'unknown'

class Uncheckable(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code or reason_code(message)

class Damaged(Exception):
    pass


def dependencies():
    result = {name: {'path': shutil.which(name), 'package': package} for name, package in TOOLS.items()}
    try:
        from PIL import features
        available = features.check('webp')
    except ImportError:
        available = False
    result['Pillow WebP (alle Einzelbilder)'] = {'path': 'verfügbar' if available else None, 'package': 'python3-pil'}
    return result


def signature(st):
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


def digest(fd):
    h = hashlib.sha256()
    offset = 0
    while True:
        chunk = os.pread(fd, 1024 * 1024, offset)
        if not chunk:
            return h.digest()
        h.update(chunk)
        offset += len(chunk)


@contextlib.contextmanager
def directory(root, relative=''):
    """Walk every component using O_NOFOLLOW, including the configured root."""
    parts = Path(root).parts[1:] + Path(relative).parts
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts:
            if part in ('..', '.') or '/' in part:
                raise Uncheckable('Ungültiger Pfad')
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        yield fd
    finally:
        os.close(fd)


@contextlib.contextmanager
def opened(parent, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise Uncheckable('Keine reguläre Datei')
        yield fd
    finally:
        os.close(fd)


def run(tool, args, fd, capture=True):
    executable = sys.executable if tool in ('pillow-webp', 'pillow-media') else shutil.which(tool)
    if tool == 'pillow-media':
        args = [str(Path(__file__).with_name('media_decode.py')), *args]
    if tool == 'pillow-webp':
        args = [str(Path(__file__).with_name('webp_decode.py')), *args]
    if not executable:
        raise Uncheckable(f'{tool} fehlt (Debian-Paket: {TOOLS[tool]})')
    # Bounded diagnostic capture on disk; image pixels go directly to /dev/null.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            result = subprocess.run([executable, *args, f'/proc/self/fd/{fd}'],
                                    pass_fds=(fd,), stdin=subprocess.DEVNULL,
                                    stdout=out if capture else subprocess.DEVNULL,
                                    stderr=err, timeout=180, env={**os.environ, 'LC_ALL': 'C', 'OMP_NUM_THREADS': '1'})
        except subprocess.TimeoutExpired as exc:
            raise Uncheckable(f'{tool}: Zeitlimit 180 Sekunden überschritten') from exc
        out.seek(0); err.seek(0)
        stdout = out.read(1024 * 1024).decode('utf-8', 'replace')
        stderr = err.read(16384).decode('utf-8', 'replace')
    return result.returncode, stdout, stderr


def metadata(fd):
    rc, out, err = run('exiftool', ['-json', '-n', '-XMP-xmpMM:HistoryParameters', '-MIMEType',
        '-ImageWidth', '-ImageHeight', '-ExifImageWidth', '-ExifImageHeight', '-DateTimeOriginal',
        '-Make', '-Model', '-DNGVersion', '-Error', '-Warning'], fd)
    if rc or err.strip():
        raise Uncheckable('ExifTool: ' + (err or out)[:2000])
    try:
        data = json.loads(out)[0]
    except (ValueError, IndexError, TypeError) as exc:
        raise Uncheckable('ExifTool: ungültige Ausgabe') from exc
    if data.get('Error'):
        raise Damaged('ExifTool: ' + str(data['Error']))
    # These notices concern auxiliary metadata, not the required provenance,
    # dimensions or decoded JPEG pixels. Unknown warnings remain blocking.
    warning = str(data.get('Warning', ''))
    allowed = (
        '[minor] Fixed incorrect URI for xmlns:MicrosoftPhoto',
        '[Minor] Not decoding some large array(s). Ignore minor errors to decode',
        'IPTCDigest is not current. XMP may be out of sync',
    )
    maker_notice = re.fullmatch(
        r'(?:\[minor\] )?(?:Maker notes could not be parsed|'
        r'Bad offset for MakerNotes tag 0x[0-9a-f]+|'
        r'Possibly incorrect maker notes offsets \(fix by [-+]?\d+\?\)|'
        r'Adjusted MakerNotes base by [-+]?\d+|Unrecognized MakerNotes|'
        r'Invalid CanonCameraSettings data)', warning, flags=re.IGNORECASE)
    if warning and warning not in allowed and not maker_notice:
        raise Uncheckable('ExifTool-Warnung: ' + str(data['Warning']))
    return data


def converted(data):
    value = data.get('HistoryParameters', [])
    return any(HISTORY in str(item) for item in (value if isinstance(value, list) else [value]))


def decode(fd, ext):
    if os.fstat(fd).st_size == 0:
        raise Damaged('Leere Datei')
    if ext in {'.jpg', '.jpeg'}:
        rc, out, err = run('jpeginfo', ['-c'], fd)
        if rc or err.strip() or not re.search(r'\bOK\b', out) or re.search(r'\b(WARNING|ERROR)\b', out):
            raise Damaged('jpeginfo: ' + (out + err)[:2000])
    elif ext == '.png':
        rc, out, err = run('pngcheck', [], fd)
        # Debian pngcheck may warn about its compile-time zlib version on every
        # healthy image. This exact library notice is not an image-data warning.
        meaningful = re.sub(r'zlib warning:  different version \(expected [0-9.]+, using [0-9.]+\)', '', err).strip()
        if rc or meaningful:
            raise Damaged('pngcheck: ' + (out + err)[:2000])
    elif ext in {'.tif', '.tiff'}:
        rc, out, err = run('tiffinfo', ['-D'], fd, capture=False)
        if rc:
            raise Damaged('tiffinfo: ' + err[:2000])
        if err.strip():
            raise Uncheckable('tiffinfo-Warnung: ' + err[:2000])
    elif ext == '.webp':
        rc, out, err = run('webpinfo', ['-diag'], fd)
        if rc or err.strip():
            raise Damaged('WebP-Struktur: ' + (out + err)[:2000])
        rc, out, err = run('pillow-webp', [], fd)
        try:
            data = json.loads(out)
        except ValueError as exc:
            raise Uncheckable('WebP-Decoder liefert kein Ergebnis: ' + err[:2000], 'decoder_warning') from exc
        if rc == 3:
            raise Uncheckable('WebP: ' + data.get('reason', err), data.get('code', 'unknown'))
        if rc or err.strip():
            raise Damaged('WebP-Bilddaten: ' + data.get('reason', err))
    elif ext in {'.gif', '.bmp', '.heic', '.heif', '.avif'}:
        rc, out, err = run('pillow-media', [ext], fd)
        try: result = json.loads(out)
        except ValueError: raise Uncheckable('Bilddecoder liefert kein Ergebnis: ' + err[:1000])
        if rc == 3: raise Uncheckable(result.get('reason', 'Decoder nicht verfügbar'))
        if rc or err.strip(): raise Damaged(result.get('reason', err))
    elif ext in RAW:
        data = metadata(fd)
        if data.get('Warning'):
            raise Uncheckable('ExifTool-Warnung: ' + str(data['Warning']))
        rc, out, err = run('dcraw_emu', ['-q', '0', '-Z', '-'], fd, capture=False)
        if rc or err.strip():
            # Unsupported camera/compression is not proof of a damaged file.
            raise Uncheckable('LibRaw: ' + (err or f'Rückgabewert {rc}')[:2000])
    else:
        raise Uncheckable('Für dieses Bildformat ist kein vollständiger Decoder eingerichtet')


def plausible(dng, jpg):
    if not dng.get('DNGVersion') or jpg.get('MIMEType') != 'image/jpeg':
        return False, 'DNG/JPEG-Dateityp nicht eindeutig bestätigt'
    dims = lambda m: (m.get('ImageWidth'), m.get('ImageHeight'))
    d, j = dims(dng), dims(jpg)
    if not all(isinstance(v, (int, float)) and v > 0 for v in d + j) or d != j:
        return False, 'Auflösung fehlt oder stimmt nicht überein'
    differences = []
    for key in ('DateTimeOriginal', 'Make', 'Model'):
        if dng.get(key) and jpg.get(key) and str(dng[key]).strip().casefold() != str(jpg[key]).strip().casefold():
            differences.append(key)
    reason = 'JPEG vollständig geprüft; Auflösung passt; Zuordnung über identischen Dateistamm'
    if differences:
        reason += '; Metadatenabweichung (kein Zuordnungsausschluss): ' + ', '.join(differences)
    return True, reason


def pairing(parent, name, dng):
    if not converted(dng):
        return 5, None, False, 'Kein expliziter JPEG→DNG-Nachweis in XMP-HistoryParameters'
    stem = Path(name).stem
    # Match stem exactly, extension case-insensitively; ambiguous matches protect DNG.
    candidates = [n for n in os.listdir(parent) if Path(n).stem == stem and Path(n).suffix.lower() in {'.jpg', '.jpeg'}]
    if not candidates:
        return 3, None, False, 'Gleichnamiges JPG/JPEG fehlt'
    if len(candidates) != 1:
        return 4, None, False, 'Mehrere passende JPG/JPEG-Dateien: Zuordnung nicht eindeutig'
    jpg = candidates[0]
    try:
        with opened(parent, jpg) as fd:
            before = signature(os.fstat(fd))
            decode(fd, '.jpg')
            data = metadata(fd)
            if signature(os.fstat(fd)) != before:
                raise Uncheckable('JPEG während Prüfung verändert')
            safe, reason = plausible(dng, data)
            notices = [str(m['Warning']) for m in (dng, data) if m.get('Warning')]
            if notices:
                reason += '; Nebenmetadatenhinweise: ' + ' / '.join(notices)
            return 2, jpg, safe, reason
    except (OSError, Uncheckable, Damaged) as exc:
        return 4, jpg, False, 'JPG defekt oder nicht sicher prüfbar: ' + str(exc)


def inspect(root, relative):
    path = Path(relative)
    result = dict(status='uncheckable', reason='', category=None, jpeg=None, safe=False)
    try:
        with directory(root, str(path.parent)) as parent, opened(parent, path.name) as fd:
            before = signature(os.fstat(fd))
            try:
                decode(fd, path.suffix.lower())
                result.update(status='ok', reason='Bilddaten vollständig gelesen')
            except Damaged as exc:
                result.update(status='damaged', reason=str(exc))
            except Uncheckable as exc:
                result['reason'] = str(exc)
                result['reason_code'] = exc.code
            if path.suffix.lower() == '.dng':
                try:
                    data = metadata(fd)
                    cat, jpg, safe, reason = pairing(parent, path.name, data)
                    result.update(category=cat, jpeg=jpg, safe=safe)
                    result['reason'] += '; ' + reason
                except (Damaged, Uncheckable) as exc:
                    result.update(category=5, safe=False)
                    result['reason'] += '; DNG-Zuordnung ungeklärt: ' + str(exc)
            if signature(os.fstat(fd)) != before:
                result.update(status='uncheckable', safe=False, reason='Datei während Prüfung verändert', reason_code='changed')
    except (OSError, Uncheckable) as exc:
        result.update(safe=False, reason=str(exc), reason_code=getattr(exc, 'code', 'access'))
    if result['status'] != 'uncheckable' or 'reason_code' not in result:
        result['reason_code'] = reason_code(result['reason'], result['status'])
    return result


def package_snapshot(root, relative, jpeg):
    """Preview footprint + content identities, including the retained JPEG."""
    path = Path(relative)
    with directory(root, str(path.parent)) as parent:
        names = os.listdir(parent)
        sidecars = [n for n in names if Path(n).suffix.lower() == '.xmp' and Path(n).stem in {path.name, path.stem}]
        if any(n != path.name and Path(n).stem.casefold() == path.stem.casefold()
               and Path(n).suffix.lower() in RAW for n in names) and (path.stem + '.xmp').casefold() in [n.casefold() for n in sidecars]:
            raise Uncheckable('XMP wird möglicherweise von anderem RAW/DNG verwendet')
        entries = {}
        size = 0
        for name in [path.name, jpeg, *sidecars]:
            with opened(parent, name) as fd:
                before = signature(os.fstat(fd))
                content = digest(fd).hex()
                if signature(os.fstat(fd)) != before:
                    raise Uncheckable('Datei während Vorschau verändert')
                entries[name] = [list(before), content]
                if name != jpeg:
                    size += before[2]
        return {'entries': entries, 'bytes': size, 'xmp': len(sidecars), 'jpeg': jpeg}


def snapshot_matches(expected, current):
    """st_dev is boot/mount-local; retain every other stamp and full content hash.

    The live checks during unlink still compare complete signatures including
    device IDs, so a mount/identity change during deletion remains blocking.
    """
    if any(expected.get(k) != current.get(k) for k in ('bytes', 'xmp', 'jpeg')):
        return False
    old, new = expected.get('entries', {}), current.get('entries', {})
    if not old or old.keys() != new.keys():
        return False
    return all(a[0][1:] == new[name][0][1:] and a[1] == new[name][1]
               for name, a in old.items())


def delete_safe(root, relative, audit, expected=None):
    """Fresh verification, pinned descriptors and identity checks before each unlink.

    Concurrent external writers cannot be made transactional with POSIX unlink;
    users must leave the collection idle during cleanup (documented in the UI).
    """
    path = Path(relative)
    if path.suffix.lower() != '.dng':
        raise Uncheckable('Nur DNG-Dateien dürfen bereinigt werden')
    if expected is not None and not snapshot_matches(expected, package_snapshot(root, relative, expected['jpeg'])):
        raise Uncheckable('Dateipaket seit bestätigter Vorschau verändert')
    with directory(root, str(path.parent)) as parent, opened(parent, path.name) as dfd:
        ds = signature(os.fstat(dfd))
        dh = digest(dfd)
        data = metadata(dfd)
        cat, jpg, safe, reason = pairing(parent, path.name, data)
        if cat != 2 or not safe:
            raise Uncheckable(reason)
        with opened(parent, jpg) as jfd:
            js = signature(os.fstat(jfd))
            jh = digest(jfd)
            decode(jfd, '.jpg')
            ok, reason = plausible(data, metadata(jfd))
            if not ok:
                raise Uncheckable(reason)
            sidecars = [n for n in os.listdir(parent)
                        if Path(n).suffix.lower() == '.xmp' and Path(n).stem in {path.name, path.stem}]
            # Shared stem sidecars must not be removed if another RAW/DNG uses them.
            siblings = [n for n in os.listdir(parent) if n != path.name
                        and Path(n).stem.casefold() == path.stem.casefold()
                        and Path(n).suffix.lower() in RAW]
            if siblings and any(n.lower() == (path.stem + '.xmp').lower() for n in sidecars):
                raise Uncheckable('Gleichnamiges XMP wird möglicherweise von anderem RAW/DNG verwendet')
            stamps = {}
            for name in sidecars:
                with opened(parent, name) as sfd:
                    stamps[name] = signature(os.fstat(sfd))
            def unchanged():
                if expected is not None and not snapshot_matches(expected, package_snapshot(root, relative, jpg)):
                    raise Uncheckable('Dateipaket seit bestätigter Vorschau verändert')
                for name, stamp in [(path.name, ds), (jpg, js), *stamps.items()]:
                    if signature(os.stat(name, dir_fd=parent, follow_symlinks=False)) != stamp:
                        raise Uncheckable('Datei seit Prüfung verändert: ' + name)
                if digest(dfd) != dh or digest(jfd) != jh:
                    raise Uncheckable('Dateiinhalt seit Prüfung verändert')
                if signature(os.fstat(dfd)) != ds or signature(os.fstat(jfd)) != js:
                    raise Uncheckable('Datei während Prüfung verändert')
                # Confirm the parent still belongs to the configured root.
                with directory(root, str(path.parent)) as current:
                    if os.fstat(current).st_ino != os.fstat(parent).st_ino or os.fstat(current).st_dev != os.fstat(parent).st_dev:
                        raise Uncheckable('Verzeichnis während Prüfung verändert')
            unchanged()
            audit(relative, 'delete-intent', 'Frisch geprüftes DNG und zugehörige XMP')
            unchanged()
            os.unlink(path.name, dir_fd=parent)
            audit(relative, 'deleted', 'DNG gelöscht; JPEG bleibt erhalten')
            for name, stamp in stamps.items():
                if signature(os.fstat(jfd)) != js or signature(os.stat(jpg, dir_fd=parent, follow_symlinks=False)) != js:
                    raise Uncheckable('JPEG verändert; restliche XMP bleiben erhalten')
                if signature(os.stat(name, dir_fd=parent, follow_symlinks=False)) != stamp:
                    raise Uncheckable('XMP verändert; bleibt erhalten')
                audit(str(path.parent / name), 'delete-intent', 'Zugehöriges XMP')
                if signature(os.stat(name, dir_fd=parent, follow_symlinks=False)) != stamp:
                    raise Uncheckable('XMP vor Löschung verändert')
                os.unlink(name, dir_fd=parent)
                audit(str(path.parent / name), 'deleted', 'Zugehöriges XMP gelöscht')
