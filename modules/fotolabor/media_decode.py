"""Bounded decoder subprocess for GIF/BMP and all libheif output images."""
import json,sys,tempfile,subprocess,shutil,warnings,resource
from pathlib import Path


def main():
    try:
        from PIL import Image
    except ImportError:
        print(json.dumps({'reason':'python3-pil fehlt'}));return 3
    ext,path=sys.argv[1:3]
    try:
        warnings.simplefilter('error',Image.DecompressionBombWarning)
        if ext in ('.gif','.bmp'):
            with Image.open(path) as im:
                if im.format != ('.gif'==ext and 'GIF' or 'BMP'):raise ValueError('Dateityp widerspricht Endung')
                frames=getattr(im,'n_frames',1)
                for i in range(frames):im.seek(i);im.load()
        else:
            tool=shutil.which('heif-convert')
            if not tool:
                print(json.dumps({'reason':'heif-convert fehlt (Debian-Paket libheif-examples)'}));return 3
            resource.setrlimit(resource.RLIMIT_FSIZE,(1024**3,1024**3))
            with tempfile.TemporaryDirectory(prefix='fotolabor-heif-') as work:
                p=subprocess.run([tool,'--with-aux',path,str(Path(work)/'image.png')],capture_output=True,timeout=150,pass_fds=(int(Path(path).name),))
                if p.returncode:
                    reason=p.stderr.decode('utf8','replace')[-2000:]
                    print(json.dumps({'reason':reason or 'HEIF-Dekodierung fehlgeschlagen'}))
                    return 3 if any(x in reason.lower() for x in ('unsupported','no decoder','plugin','memory','limit')) else 2
                images=list(Path(work).glob('*.png'))
                if not images:raise ValueError('Keine dekodierten Bilder')
                frames=len(images)
                for image in images:
                    with Image.open(image) as im:im.load()
        print(json.dumps({'frames':frames}));return 0
    except (MemoryError,Image.DecompressionBombWarning,Image.DecompressionBombError,subprocess.TimeoutExpired) as exc:
        print(json.dumps({'reason':str(exc)}));return 3
    except Exception as exc:
        print(json.dumps({'reason':str(exc)}));return 2

if __name__=='__main__':sys.exit(main())
