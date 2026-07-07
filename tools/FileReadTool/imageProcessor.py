from __future__ import annotations

import base64
import io
import math
from pathlib import Path
from typing import Any

try:
    from PIL import Image
except ImportError:  # pragma: no cover - Pillow is available in the dev env.
    Image = None


DEFAULT_MAX_EDGE = 1568
EDGE_STEPS = [1568, 1280, 1024, 768, 512, 384, 256]
QUALITY_STEPS = [85, 75, 65, 50, 35, 25]
RESAMPLING_LANCZOS = (
    getattr(getattr(Image, 'Resampling', Image), 'LANCZOS', None)
    if Image is not None
    else None
)

_MEDIA_ALIASES = {
    'jpg': 'jpeg',
    'jpeg': 'jpeg',
    'png': 'png',
    'gif': 'gif',
    'webp': 'webp',
    'bmp': 'png',
}


def _require_pillow() -> None:
    if Image is None:
        raise RuntimeError('Image support requires Pillow to be installed.')


def _estimate_tokens(base64_data: str) -> int:
    return int(math.ceil(len(base64_data) * 0.125))


def _has_alpha(image: Any) -> bool:
    bands = set(getattr(image, 'getbands', lambda: ())())
    if 'A' in bands:
        return True
    return bool(image.info.get('transparency'))


def _normalized_media_suffix(format_name: str | None) -> str:
    normalized = (format_name or 'png').lower()
    return _MEDIA_ALIASES.get(normalized, normalized)


def detect_image_media_type(raw: bytes) -> str:
    _require_pillow()
    with Image.open(io.BytesIO(raw)) as image:
        return f'image/{_normalized_media_suffix(image.format)}'


def _choose_output_format(image: Any, detected_format: str) -> str:
    normalized = _normalized_media_suffix(detected_format)
    if _has_alpha(image):
        return 'png'
    if normalized in {'jpeg', 'png', 'webp', 'gif'}:
        return normalized
    return 'jpeg'


def _resize_dimensions(width: int, height: int, max_edge: int) -> tuple[int, int]:
    if max(width, height) <= max_edge:
        return width, height
    scale = max_edge / float(max(width, height))
    return max(1, int(round(width * scale))), max(1, int(round(height * scale)))


def _prepare_image(image: Any, output_format: str) -> Any:
    if output_format == 'jpeg' and image.mode not in {'RGB', 'L'}:
        return image.convert('RGB')
    if output_format == 'png' and image.mode == 'P' and _has_alpha(image):
        return image.convert('RGBA')
    return image


def _save_image(image: Any, output_format: str, quality: int) -> bytes:
    buffer = io.BytesIO()
    if output_format == 'jpeg':
        image.save(buffer, format='JPEG', quality=quality, optimize=True)
    elif output_format == 'png':
        image.save(buffer, format='PNG', optimize=True, compress_level=9)
    elif output_format == 'webp':
        image.save(buffer, format='WEBP', quality=quality, method=6)
    elif output_format == 'gif':
        image.save(buffer, format='GIF', optimize=True)
    else:
        image.save(buffer, format=output_format.upper())
    return buffer.getvalue()


def maybe_resize_and_downsample_image_bytes(
    raw: bytes,
    original_size: int,
    detected_format: str,
    *,
    max_edge: int = DEFAULT_MAX_EDGE,
    quality: int = 85,
) -> dict[str, Any]:
    _require_pillow()
    with Image.open(io.BytesIO(raw)) as image:
        width, height = image.size
        display_width, display_height = _resize_dimensions(width, height, max_edge)
        output_format = _choose_output_format(image, detected_format)

        if (display_width, display_height) != (width, height):
            resized = image.resize((display_width, display_height), RESAMPLING_LANCZOS)
        else:
            resized = image.copy()
        try:
            prepared = _prepare_image(resized, output_format)
            output = _save_image(prepared, output_format, quality)
        finally:
            resized.close()

    return {
        'buffer': output,
        'mediaType': output_format,
        'dimensions': {
            'originalWidth': width,
            'originalHeight': height,
            'displayWidth': display_width,
            'displayHeight': display_height,
        },
        'originalSize': original_size,
    }


def compress_image_with_token_limit(
    raw: bytes,
    max_tokens: int,
    detected_media_type: str,
) -> dict[str, Any]:
    detected_format = detected_media_type.split('/', 1)[-1] or 'png'
    best: dict[str, Any] | None = None

    for edge in EDGE_STEPS:
        for quality in QUALITY_STEPS:
            candidate = maybe_resize_and_downsample_image_bytes(
                raw,
                len(raw),
                detected_format,
                max_edge=edge,
                quality=quality,
            )
            base64_data = base64.b64encode(candidate['buffer']).decode('ascii')
            score = _estimate_tokens(base64_data)
            entry = {
                'base64': base64_data,
                'mediaType': f"image/{candidate['mediaType']}",
                'dimensions': candidate.get('dimensions'),
                'estimatedTokens': score,
            }
            if best is None or score < best['estimatedTokens']:
                best = entry
            if score <= max_tokens:
                return entry

    if best is None:
        raise RuntimeError('Unable to compress image content.')
    return best


def read_image_metadata(file_path: str, token_limit: int = 4096) -> dict[str, Any]:
    path = Path(file_path)
    raw = path.read_bytes()
    detected_media_type = detect_image_media_type(raw)
    detected_format = detected_media_type.split('/', 1)[-1]

    resized = maybe_resize_and_downsample_image_bytes(
        raw,
        len(raw),
        detected_format,
    )
    preview_base64 = base64.b64encode(resized['buffer']).decode('ascii')
    if _estimate_tokens(preview_base64) > token_limit:
        compressed = compress_image_with_token_limit(raw, token_limit, detected_media_type)
        preview_base64 = compressed['base64']
        detected_media_type = compressed['mediaType']
        dimensions = compressed.get('dimensions')
    else:
        dimensions = resized.get('dimensions')

    return {
        'filePath': str(path),
        'bytes': len(raw),
        'tokenLimit': token_limit,
        'previewBase64': preview_base64,
        'truncatedPreview': _estimate_tokens(preview_base64) > token_limit,
        'mediaType': detected_media_type,
        'dimensions': dimensions,
    }


__all__ = [
    'DEFAULT_MAX_EDGE',
    'compress_image_with_token_limit',
    'detect_image_media_type',
    'maybe_resize_and_downsample_image_bytes',
    'read_image_metadata',
]
