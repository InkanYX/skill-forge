"""Bounded image previews and conservative, structured automatic reviews."""
from __future__ import annotations

import io
from typing import Literal

from PIL import Image, ImageOps
from pydantic import BaseModel, Field, ValidationError


CHECKS = ('structure', 'quantity', 'proportion', 'material', 'color', 'text', 'lighting', 'requirements')
REVIEW_INSTRUCTIONS = """请对照制作目标、实际提示词和参考图（如有），检查生成图。
必须覆盖 structure（结构）、quantity（数量）、proportion（比例）、material（材质）、
color（颜色）、text（文案）、lighting（光影）、requirements（制作要求）八项。
参考图是产品身份依据；不得把生成图中新增的特征当成原产品事实。
用户明确要求改变的颜色、背景或部位，以本轮最新要求为准；检查其它特征是否保持，不得把获准的变化误判为错误。
无法确认的项目标 uncertain；明确有问题标 rework；确实符合要求标 passed。
不适用的项目也需列出并解释。只返回 JSON，不要附加文字：
{"status":"passed|rework|uncertain","summary":"结论",
 "checks":[{"item":"structure","status":"passed|rework|uncertain","detail":"依据"}, ...]}
"""


class ReviewCheck(BaseModel):
    item: str = Field(max_length=40)
    status: Literal['passed', 'rework', 'uncertain']
    detail: str = Field(min_length=1, max_length=2000)


class VisionReview(BaseModel):
    status: Literal['passed', 'rework', 'uncertain']
    summary: str = Field(min_length=1, max_length=4000)
    checks: list[ReviewCheck] = Field(min_length=1, max_length=16)


def jpeg_preview(content: bytes) -> bytes:
    """Never send a full native PNG to the planning/review model."""
    with Image.open(io.BytesIO(content)) as source:
        image = ImageOps.exif_transpose(source).convert('RGBA')
        image.thumbnail((1280, 1280))
        background = Image.new('RGBA', image.size, 'white')
        background.alpha_composite(image)
        output = io.BytesIO()
        background.convert('RGB').save(output, 'JPEG', quality=80, optimize=True)
        return output.getvalue()


def parse_review(raw: str) -> dict:
    """A free-form reply or an incomplete checklist can never count as passing."""
    text = raw.strip()
    if text.startswith('```') and text.endswith('```'):
        text = text.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
    try:
        review = VisionReview.model_validate_json(text)
    except (ValidationError, ValueError):
        return {'status': 'uncertain', 'summary': '视觉模型未返回完整质检记录，待人工审核。', 'checks': []}
    result = review.model_dump()
    by_item = {item.item: item.status for item in review.checks}
    if review.status == 'rework' or any(item.status == 'rework' for item in review.checks):
        result['status'] = 'rework'
    elif (review.status != 'passed' or set(by_item) != set(CHECKS)
          or len(by_item) != len(review.checks)
          or any(item.status != 'passed' for item in review.checks)):
        result['status'] = 'uncertain'
        result['summary'] = '质检项目存在缺失或不确定，待人工审核。' + review.summary
    return result
