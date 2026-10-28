"""Bounded format checks, not an antivirus or a content classifier."""

import codecs
from pathlib import Path
import warnings

from PIL import Image


def validate_file(path, name):
    path = Path(path)
    with path.open('rb') as stream:
        head = stream.read(65536)
    ext = Path(name).suffix.lower()
    if head.startswith((b'MZ', b'\x7fELF', b'PK\x03\x04')):
        raise ValueError('The file contents do not match the permitted attachment format.')
    if ext in {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.avif'}:
        expected = {'.jpg': 'JPEG', '.jpeg': 'JPEG'}.get(ext, ext[1:].upper())
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(path) as image:
                    if image.format != expected or image.width * image.height > 20_000_000 or max(image.size) > 8192:
                        raise ValueError('The image format or dimensions are outside the sharing limits.')
                    image.verify()
        except (OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
            raise ValueError('The attachment is not a valid image in its declared format.') from error
        return
    checks = {
        '.pdf': b'%PDF-' in head[:1024],
        '.mp4': head[4:8] == b'ftyp', '.m4v': head[4:8] == b'ftyp',
        '.m4a': head[4:8] == b'ftyp',
        '.mov': head[4:8] in {b'ftyp', b'moov', b'mdat', b'wide'},
        '.webm': head.startswith(b'\x1aE\xdf\xa3'),
        '.ogg': head.startswith(b'OggS'), '.oga': head.startswith(b'OggS'),
        '.wav': head.startswith(b'RIFF') and head[8:12] == b'WAVE',
        '.flac': head.startswith(b'fLaC'),
        '.mp3': head.startswith(b'ID3') or (len(head)>1 and head[0]==255 and head[1]&224==224),
    }
    if ext == '.txt':
        try:
            encoding = 'utf-16' if head.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
            text = codecs.getincrementaldecoder(encoding)().decode(head, final=False)
            if '\x00' in text or any(ord(c)<32 and c not in '\r\n\t\f' for c in text):
                raise ValueError('Binary content cannot be shared as a TXT file.')
        except UnicodeError as error:
            raise ValueError('TXT attachments must use UTF-8 or UTF-16 text.') from error
        return
    if not checks.get(ext, False):
        raise ValueError('The file contents do not match its declared format.')
