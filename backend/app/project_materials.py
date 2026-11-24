"""Immutable originals plus small previews and page-addressable PDF evidence."""
import hashlib
import io
from pathlib import Path
from uuid import UUID

from PIL import Image, ImageOps
from fastapi import HTTPException
from pypdf import PdfReader

from app.image_provider import normalize_image, GenerationError, MAX_IMAGE

MAX_ASSETS = 24
MAX_PAGES = 40


def project_root(directory: Path, identifier: str) -> Path:
    return directory / 'product-projects' / str(UUID(identifier))


def asset_root(directory, project_id, asset_id):
    return project_root(directory, project_id) / 'assets' / str(UUID(asset_id))


def jpeg_preview(content: bytes) -> bytes:
    with Image.open(io.BytesIO(content)) as source:
        image = ImageOps.exif_transpose(source).convert('RGBA')
        image.thumbnail((1024, 1024))
        background = Image.new('RGB', image.size, 'white')
        background.paste(image, mask=image.getchannel('A'))
        output = io.BytesIO()
        background.save(output, 'JPEG', quality=75, optimize=True)
        return output.getvalue()


def prepare_asset(content, filename, role, identifier):
    if not content or len(content) > MAX_IMAGE:
        raise HTTPException(422, '每份资料需在 20 MB 以内。')
    name = (filename or '资料').replace('\\', '/').split('/')[-1][:120]
    pdf = content.startswith(b'%PDF-')
    asset = {'id': identifier, 'name': name, 'role': role, 'kind': 'pdf' if pdf else 'image',
             'sha256': hashlib.sha256(content).hexdigest(), 'bytes': len(content), 'analysis': ''}
    files = {'original.pdf' if pdf else 'original.bin': content}
    if pdf:
        if role not in ('manual', 'specification'):
            raise HTTPException(422, 'PDF 请选说明书或规格书角色。')
        try:
            reader = PdfReader(io.BytesIO(content))
            if reader.is_encrypted:
                raise ValueError('encrypted')
            if not 1 <= len(reader.pages) <= MAX_PAGES:
                raise ValueError('pages')
            pages = []
            for index, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ''
                if len(text) > 20000:
                    raise ValueError('page text')
                pages.append({'page': index, 'text': text, 'analysis': '', 'method': 'text+vision_pending'})
            if sum(len(p['text']) for p in pages) > 120000:
                raise ValueError('text')
            asset['pages'] = pages
        except Exception:
            raise HTTPException(422, 'PDF 无法读取、已加密或超过 40 页/12 万字，请解密或拆分后上传。') from None
    else:
        if role not in ('product_identity', 'owned_artwork', 'approved_copy'):
            raise HTTPException(422, '图片请选择产品身份、品牌风格或已批准文案角色。')
        try:
            normalized = normalize_image(content)
            files['input.png'] = normalized
            files['preview.jpg'] = jpeg_preview(normalized)
            asset['input_sha256'] = hashlib.sha256(normalized).hexdigest()
        except GenerationError as error:
            raise HTTPException(422, error.message) from None
    return asset, files


def page_preview(directory, project_id, asset_id, page_number):
    """Render one page at a time; no concatenated multi-page image uploads."""
    import pypdfium2 as pdfium
    root = asset_root(directory, project_id, asset_id)
    output = root / f'page-{page_number}.jpg'
    if output.is_file():
        return output.read_bytes()
    document = pdfium.PdfDocument(str(root / 'original.pdf'))
    try:
        page = document[page_number - 1]
        try:
            width, height = page.get_size()
            bitmap = page.render(scale=min(2, 1400 / max(width, height)))
            try:
                data = io.BytesIO()
                bitmap.to_pil().convert('RGB').save(data, 'JPEG', quality=80, optimize=True)
                content = data.getvalue()
            finally:
                bitmap.close()
        finally:
            page.close()
    finally:
        document.close()
    output.write_bytes(content)
    return content
