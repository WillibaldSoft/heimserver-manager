import sys,warnings
from PIL import Image
warnings.simplefilter('error',Image.DecompressionBombWarning)
with Image.open(sys.argv[1]) as im:
    im.load()
    im.convert('RGB').save(sys.argv[2],format='JPEG',quality=95,subsampling=0)
with Image.open(sys.argv[2]) as check:
    check.load()
