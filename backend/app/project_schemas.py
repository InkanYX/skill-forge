"""Validated stage artifacts. AI content is data, never executable instructions."""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ProjectInput(StrictModel):
    title: str = Field(min_length=1, max_length=120)
    sku: str = Field(min_length=1, max_length=100)
    brief: str = Field(default='', max_length=8000)
    skill_id: UUID
    config_id: UUID
    image_model_name: str = Field(default='gpt-image-2.5-sunburst', max_length=200)
    image_count: int = Field(default=6, ge=1, le=8)

    @field_validator('title', 'sku', 'image_model_name')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('不能为空。')
        return value.strip()


class VersionInput(StrictModel):
    revision: int = Field(ge=1)


class Command(VersionInput):
    action: Literal['analyze', 'discuss_points', 'approve_points', 'plan', 'discuss_plan', 'generate', 'resume', 'cancel']
    message: str = Field(default='', max_length=8000)
    point_ids: list[str] = Field(default_factory=list, max_length=30)
    authorized: bool = False


class Claim(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=1800)
    source_ids: list[str] = Field(min_length=1, max_length=12)
    status: Literal['supported', 'photo_inference', 'needs_evidence', 'conflict']
    boundary: str = Field(default='', max_length=1800)


class SellingPoint(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    feature: str = Field(min_length=1, max_length=1500)
    benefit: str = Field(min_length=1, max_length=1500)
    claim_ids: list[str] = Field(min_length=1, max_length=12)
    status: Literal['supported', 'photo_inference', 'needs_evidence', 'conflict']
    visual: str = Field(min_length=1, max_length=1800)
    conditions: str = Field(default='', max_length=1800)
    priority: Literal['primary', 'secondary', 'specification', 'excluded'] = 'secondary'


class PointsArtifact(StrictModel):
    summary: str = Field(max_length=4000)
    identity: str = Field(min_length=1, max_length=6000)
    claims: list[Claim] = Field(min_length=1, max_length=80)
    points: list[SellingPoint] = Field(min_length=1, max_length=30)
    unknowns: list[str] = Field(default_factory=list, max_length=40)


class CopyItem(StrictModel):
    text: str = Field(min_length=1, max_length=600)
    claim_ids: list[str] = Field(default_factory=list, max_length=12)


class Shot(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=100)
    kind: Literal['main', 'secondary', 'a-plus'] = 'secondary'
    question: str = Field(min_length=1, max_length=1200)
    point_ids: list[str] = Field(min_length=1, max_length=12)
    claim_ids: list[str] = Field(min_length=1, max_length=20)
    scene: str = Field(min_length=1, max_length=2500)
    camera: str = Field(min_length=1, max_length=1800)
    composition: str = Field(min_length=1, max_length=2500)
    lighting: str = Field(min_length=1, max_length=1800)
    props: str = Field(min_length=1, max_length=1800)
    copy_items: list[CopyItem] = Field(default_factory=list, max_length=12, alias='copy')
    typography: str = Field(min_length=1, max_length=1800)
    reference_asset_id: str = Field(min_length=1, max_length=80)
    aspect_ratio: str = Field(default='1:1', pattern=r'^\d{1,4}:\d{1,4}$')
    acceptance: list[str] = Field(min_length=1, max_length=20)
    information_gain: str = Field(min_length=1, max_length=1800)


class PlanArtifact(StrictModel):
    summary: str = Field(max_length=4000)
    visual_system: str = Field(min_length=1, max_length=8000)
    shots: list[Shot] = Field(min_length=1, max_length=8)


class ArtifactUpdate(VersionInput):
    points: PointsArtifact | None = None
    plan: PlanArtifact | None = None


class OutputReview(VersionInput):
    status: Literal['passed', 'rework', 'pending']
    notes: str = Field(default='', max_length=4000)


def validate_points(artifact, state):
    """All claims must trace to an actual uploaded page/image or user statement."""
    sources = ({'brief'} if state['brief'].strip() else set()) | {a['id'] for a in state['assets'] if a['kind'] != 'pdf'}
    sources |= {f"{a['id']}:p{p['page']}" for a in state['assets'] for p in a.get('pages', [])}
    sources |= {m['id'] for m in state['messages'] if m['role'] == 'user'}
    claims = {c.id: c for c in artifact.claims}
    if len(claims) != len(artifact.claims) or len({p.id for p in artifact.points}) != len(artifact.points):
        raise ValueError('卖点或证据编号重复。')
    for claim in artifact.claims:
        if not set(claim.source_ids) <= sources:
            raise ValueError('证据引用了不存在的资料或页码。')
        style_only = {a['id'] for a in state['assets'] if a['role'] == 'owned_artwork'}
        if claim.status == 'supported' and set(claim.source_ids) <= style_only:
            raise ValueError('品牌风格参考不能单独证明本 SKU 的事实。')
    for point in artifact.points:
        if not set(point.claim_ids) <= claims.keys():
            raise ValueError('卖点引用了不存在的证据。')
        if point.status == 'supported' and any(claims[i].status != 'supported' for i in point.claim_ids):
            raise ValueError('待证或冲突证据不能用于已支持卖点。')


def validate_plan(artifact, state):
    points = {p['id']: p for p in state['points']['points']}
    claims = {c['id']: c for c in state['points']['claims']}
    approved = set(state['approved_point_ids'])
    identity = {a['id'] for a in state['assets'] if a['role'] == 'product_identity' and a['kind'] == 'image'}
    if len(artifact.shots) != state['image_count']:
        raise ValueError('图需张数必须等于项目约定张数。')
    if len({s.id for s in artifact.shots}) != len(artifact.shots):
        raise ValueError('图号重复。')
    for shot in artifact.shots:
        if not set(shot.point_ids) <= approved:
            raise ValueError('图需只能使用用户已确认的卖点。')
        if any(points[i]['status'] != 'supported' for i in shot.point_ids):
            raise ValueError('图需包含尚未证实的卖点。')
        if not set(shot.claim_ids) <= claims.keys() or any(claims[i]['status'] != 'supported' for i in shot.claim_ids):
            raise ValueError('图需引用了未支持的证据。')
        if not set(shot.claim_ids) <= {c for i in shot.point_ids for c in points[i]['claim_ids']}:
            raise ValueError('图需证据与确认卖点不对应。')
        if shot.reference_asset_id not in identity:
            raise ValueError('每张图必须指定本项目的产品身份实拍/商品图，不能用风格图替代。')
        if shot.kind == 'main' and shot.copy_items:
            raise ValueError('主图不能新增文案。')
        if shot.kind != 'main' and not shot.copy_items:
            raise ValueError('附图/A+ 需要逐字成品文案。')
        for item in shot.copy_items:
            if not set(item.claim_ids) <= set(shot.claim_ids):
                raise ValueError('文案引用了本图以外的证据。')
