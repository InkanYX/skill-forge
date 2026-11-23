"""Requested image dimensions; provider-specific capabilities remain external."""
import re
from typing import Annotated

from pydantic import AfterValidator, Field
from app.image_provider import MAX_PIXELS


def normalize_size(value: str) -> str:
    value = value.strip().lower()
    if value == 'default':
        return value
    match = re.fullmatch(r'([0-9]{1,8})\s*[x×]\s*([0-9]{1,8})', value)
    if not match:
        raise ValueError('尺寸请使用“宽x高”，单位为像素，例如 2000x2000；不指定尺寸请使用 default。')
    width, height = map(int, match.groups())
    if width < 1 or height < 1 or width * height > MAX_PIXELS:
        raise ValueError('宽高必须为正整数，总像素不能超过 2000 万；具体尺寸仍需服务商和模型支持。')
    return f'{width}x{height}'


ImageSize = Annotated[str, Field(min_length=1, max_length=32), AfterValidator(normalize_size)]
