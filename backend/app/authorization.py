"""Request identity and ownership checks, also enforced for ORM writes."""
from contextvars import ContextVar
from fastapi import HTTPException
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

principal = ContextVar('request_principal', default=None)

def can_edit(row):
    user = principal.get()
    return user is None or user['role'] == 'admin' or getattr(row,'owner_id',None) == user['id'] or (inspect(row).pending and not getattr(row,'owner_id',None))

def require_edit(row):
    if not can_edit(row): raise HTTPException(403, '只能修改自己创建的内容；可以查看或复制团队共享内容。')

def require_private(row):
    user = principal.get()
    if user is not None and row.owner_id != user['id']:
        raise HTTPException(404, '个人模型连接不存在。')

def owner_view(row):
    user = principal.get()
    return {'owner_id': getattr(row,'owner_id',None) or (user['id'] if user and inspect(row).pending else None), 'can_edit': can_edit(row)}

@event.listens_for(Session, 'before_flush')
def protect_writes(session, flush_context, instances):
    user = principal.get()
    if user is None: return
    from app.database import OwnedRecord, ModelConfiguration, ProductAsset, Product, CreativeCase, ImageJob
    for row in set(session.new) | set(session.dirty) | set(session.deleted):
        if not isinstance(row, OwnedRecord): continue
        if row in session.new:
            row.owner_id = user['id']
            if isinstance(row, ProductAsset):
                parent = session.get(Product, row.product_id)
                if parent: require_edit(parent)
            if isinstance(row, CreativeCase):
                parent = session.get(ImageJob, row.job_id)
                if parent: require_edit(parent)
        else:
            if isinstance(row, ModelConfiguration): require_private(row)
            else: require_edit(row)
            if inspect(row).attrs.owner_id.history.has_changes():
                raise HTTPException(403, '不能改变内容归属。')
