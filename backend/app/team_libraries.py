"""Explicit read-only team libraries, without widening personal ORM access."""
from types import SimpleNamespace
from sqlalchemy import select
from app.database import WorkflowCase, ProductImageExperience, UserAccount, CreativeCase


def shared_case(session, identifier):
    table=WorkflowCase.__table__
    value=session.execute(select(table).where(table.c.id==str(identifier))).mappings().first()
    return SimpleNamespace(**value) if value else None


def case_rows(session, query=''):
    table=WorkflowCase.__table__
    statement=select(table)
    if query.strip(): statement=statement.where(table.c.title.icontains(query.strip(),autoescape=True)|table.c.summary.icontains(query.strip(),autoescape=True))
    return [SimpleNamespace(**row) for row in session.execute(statement.order_by(table.c.created_at.desc()).limit(100)).mappings()]


def author(session, owner):
    row=session.get(UserAccount,owner) if owner else None
    return {'id':owner,'name':row.display_name if row else '原作者'}


def experience_rows(session):
    table=ProductImageExperience.__table__
    return [SimpleNamespace(**row) for row in session.execute(select(table).order_by(table.c.updated_at.desc()).limit(500)).mappings()]


def evidence_current(session, data):
    table=CreativeCase.__table__
    for source in data.get('sources',[]):
        revision=session.execute(select(table.c.revision).where(table.c.id==source['id'])).scalar()
        if revision!=source['revision']: return False
    return True
