"""No-symlink directory anchor for ACL writes."""
import os
from contextlib import contextmanager
from pathlib import Path

@contextmanager
def directory_fd(path):
    p=Path(path)
    if not p.is_absolute() or '..' in p.parts:raise ValueError('Ungültiger Ordnerpfad.')
    fd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
    try:
        for part in p.parts[1:]:
            new=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);os.close(fd);fd=new
        yield fd
    finally:os.close(fd)
