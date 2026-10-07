"""Isolated full WebP decoder; no file writes, including for animations."""
import json
import sys
import warnings


def main():
    try:
        from PIL import Image, features
        if not features.check('webp'):
            raise ImportError('Pillow ohne WebP-Unterstützung')
    except ImportError as exc:
        print(json.dumps({'code': 'missing_decoder', 'reason': str(exc)}))
        return 3
    try:
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        with Image.open(sys.argv[1]) as image:
            if image.format != 'WEBP':
                raise ValueError('Datei enthält kein WebP-Bild')
            frames = getattr(image, 'n_frames', 1)
            for index in range(frames):
                image.seek(index)
                image.load()
            print(json.dumps({'frames': frames}))
        return 0
    except (MemoryError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        print(json.dumps({'code': 'resource_limit', 'reason': str(exc)}))
        return 3
    except Exception as exc:
        print(json.dumps({'code': 'damaged', 'reason': str(exc)}))
        return 2


if __name__ == '__main__':
    sys.exit(main())
