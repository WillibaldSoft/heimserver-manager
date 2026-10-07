"""Isolated complete JPEG/MPO fingerprint, including every embedded image."""
import hashlib,json,sys,warnings
from PIL import Image
warnings.simplefilter('error')
with Image.open(sys.argv[1]) as im:
    fmt=im.format
    if fmt not in ('JPEG','MPO'):raise ValueError('Kein JPEG/MPO')
    frames=[]
    for index in range(getattr(im,'n_frames',1)):
        im.seek(index);im.load()
        frames.append(dict(size=im.size,mode=im.mode,pixels=hashlib.sha256(im.tobytes()).hexdigest(),
            icc=hashlib.sha256(im.info.get('icc_profile',b'')).hexdigest(),orientation=im.getexif().get(274,1)))
    print(json.dumps(dict(format=fmt,frames=frames)))
