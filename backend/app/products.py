from app.authorization import owner_view, require_edit
"""Product facts and immutable, normalized image assets."""
import hashlib
import json
import os
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid4
from fastapi import APIRouter, HTTPException, File, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.database import Product, ProductAsset
from app.creative_templates import timestamp
from app.image_provider import normalize_image, MAX_IMAGE, GenerationError


class ProductInput(BaseModel):
    sku: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=120)
    category: Literal['车棚', '凉棚', '其他'] = '凉棚'
    dimensions: str = Field(default='', max_length=300)
    color: str = Field(default='', max_length=200)
    facts: str = Field(default='', max_length=4000)
    notes: str = Field(default='', max_length=2000)
    revision: int = Field(default=0, ge=0)

    @field_validator('sku', 'name')
    @classmethod
    def not_blank(cls, value, info):
        if not value.strip():
            raise ValueError('SKU 和产品名称不能为空。')
        return value.strip().upper() if info.field_name == 'sku' else value.strip()


def product_view(row):
    return {**owner_view(row), **json.loads(row.content), 'id': row.id, 'sku': row.sku, 'revision': row.revision, 'updated_at': row.updated_at}


def asset_path(directory: Path, product_id: str, asset_id: str, digest: str):
    if len(digest) != 64 or any(char not in '0123456789abcdef' for char in digest):
        raise ValueError('Invalid asset digest')
    return directory / 'products' / str(UUID(product_id)) / f'{UUID(asset_id)}-{digest}.png'


def asset_view(row):
    return {'id': row.id, 'product_id': row.product_id, 'name': row.name, 'kind': row.kind, 'created_at': row.created_at, 'image_url': f'/api/products/{row.product_id}/assets/{row.id}/image'}


def resolve_product(session, directory, request, reference):
    try:
        identifier = str(UUID(request['id']))
        revision = int(request['revision'])
        asset_id = str(UUID(request['asset_id'])) if request.get('asset_id') else None
    except (ValueError, TypeError, AttributeError, KeyError):
        raise HTTPException(422, '产品参数无效。') from None
    row = session.get(Product, identifier)
    if row is None:
        raise HTTPException(404, '产品不存在。')
    if row.revision != revision:
        raise HTTPException(409, '产品资料已更新，请重新选择产品再提交。')
    snapshot = product_view(row)
    if asset_id:
        if reference is not None:
            raise HTTPException(422, '请选择素材库参考图或临时上传图中的一种。')
        asset = session.get(ProductAsset, asset_id)
        if asset is None or asset.product_id != identifier:
            raise HTTPException(422, '参考素材不属于所选产品。')
        try:
            reference = asset_path(directory, identifier, asset_id, asset.digest).read_bytes()
        except OSError:
            raise HTTPException(422, '素材文件缺失，请检查本机数据目录。') from None
        snapshot['asset'] = asset_view(asset)
    return snapshot, reference


def build_product_router(engine, directory):
    router = APIRouter(prefix='/api/products', tags=['products'])
    def require_db():
        if engine is None:
            raise HTTPException(503, '请先配置数据库并执行迁移。')

    @router.get('')
    def list_products():
        require_db()
        with Session(engine) as session:
            return [product_view(row) for row in session.scalars(select(Product).order_by(Product.updated_at.desc()))]

    def save(data, identifier=None):
        require_db()
        try:
            with Session(engine) as session, session.begin():
                if identifier:
                    row = session.get(Product, str(identifier), with_for_update=True)
                    if row is None:
                        raise HTTPException(404, '产品不存在。')
                    require_edit(row)
                    if data.revision != row.revision:
                        raise HTTPException(409, '产品已被修改，请重新载入。')
                    row.revision += 1
                else:
                    row = Product(id=str(uuid4()), revision=1)
                    session.add(row)
                row.sku = data.sku
                row.content = json.dumps(data.model_dump(exclude={'revision', 'sku'}), ensure_ascii=False)
                row.updated_at = timestamp()
                result = product_view(row)
            return result
        except IntegrityError:
            raise HTTPException(409, '该 SKU 已存在，请编辑已有产品或使用其他 SKU。') from None

    @router.post('', status_code=201)
    def create_product(data: ProductInput):
        return save(data)

    @router.put('/{identifier}')
    def update_product(identifier: UUID, data: ProductInput):
        return save(data, identifier)

    def require_product(session, identifier):
        if session.get(Product, str(identifier)) is None:
            raise HTTPException(404, '产品不存在。')

    @router.get('/{identifier}/assets')
    def list_assets(identifier: UUID):
        require_db()
        with Session(engine) as session:
            require_product(session, identifier)
            return [asset_view(row) for row in session.scalars(select(ProductAsset).where(ProductAsset.product_id == str(identifier)).order_by(ProductAsset.created_at.desc()))]

    @router.post('/{identifier}/assets', status_code=201)
    def upload_asset(identifier: UUID, asset_id: Annotated[UUID, Form()], image: Annotated[UploadFile, File()], kind: Annotated[Literal['产品实拍', '结构细节', '尺寸图', '其他'], Form()] = '产品实拍'):
        require_db()
        try:
            content = normalize_image(image.file.read(MAX_IMAGE + 1))
        except GenerationError as error:
            raise HTTPException(422, error.message) from None
        digest = hashlib.sha256(content).hexdigest()
        def same(row):
            if row is None or row.product_id != str(identifier) or row.digest != digest or row.kind != kind:
                raise HTTPException(409, '上传标识已用于其他素材，请重新选择文件。')
            return asset_view(row)
        with Session(engine) as session:
            require_product(session, identifier)
            prior = session.get(ProductAsset, str(asset_id))
            if prior:
                return same(prior)
            path = asset_path(directory, str(identifier), str(asset_id), digest)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f'{asset_id}-{uuid4()}.tmp')
            temporary.write_bytes(content)
            os.replace(temporary, path)
            name = (image.filename or '产品素材').replace('\\', '/').split('/')[-1][:120]
            row = ProductAsset(id=str(asset_id), product_id=str(identifier), name=name, kind=kind, digest=digest, created_at=timestamp())
            session.add(row)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                return same(session.get(ProductAsset, str(asset_id)))
            return asset_view(row)

    @router.get('/{identifier}/assets/{asset_id}/image')
    def get_asset(identifier: UUID, asset_id: UUID):
        require_db()
        with Session(engine) as session:
            row = session.get(ProductAsset, str(asset_id))
            if row is None or row.product_id != str(identifier):
                raise HTTPException(404, '素材不存在。')
            path = asset_path(directory, str(identifier), str(asset_id), row.digest)
        if not path.is_file():
            raise HTTPException(404, '素材文件缺失。')
        return FileResponse(path, media_type='image/png', headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
    return router
