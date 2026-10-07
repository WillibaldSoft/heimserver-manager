"""Serve the reviewed Windows build, without a compiler on the server."""
import hashlib
import json
import re
from pathlib import Path


def executable(directory=None):
    root = Path(directory) if directory is not None else Path(__file__).resolve().parent
    path = root / 'HeimserverManagerClient.exe'
    metadata = root / 'release.json'
    if path.is_symlink() or metadata.is_symlink():
        raise ValueError('Unexpected symbolic link')
    info = json.loads(metadata.read_text())
    version = info.get('version', '')
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Invalid Windows client version')
    if not 1024 <= path.stat().st_size <= 10 * 1024 * 1024:
        raise ValueError('Invalid Windows client size')
    data = path.read_bytes()
    if not data.startswith(b'MZ') or hashlib.sha256(data).hexdigest() != info.get('sha256'):
        raise ValueError('Windows client checksum mismatch')
    return data, 'Heimserver_Manager_Client_' + version + '_Windows.exe'
