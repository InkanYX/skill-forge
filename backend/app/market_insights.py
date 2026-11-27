"""Team market studies, durable metered MCP jobs and reusable source snapshots."""
import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from dotenv import dotenv_values
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import String, Text, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.database import Base
from app.sellersprite import SellerSpriteClient, ResearchError, shared_key

MARKETS = ('US', 'UK', 'DE', 'FR', 'IT', 'ES', 'JP', 'CA', 'AU', 'MX', 'BR', 'IN', 'AE')
TOOLS = {'search': 'category.search', 'overview': 'category.report.detail',
         'history': 'category.report.detail', 'distribution': 'category.trend',
         'products': 'category.top.list', 'brands': 'category.top.list'}


def now():
    return datetime.now(timezone.utc).isoformat()


class MarketStudy(Base):
    __tablename__ = 'market_studies'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(36))
    author: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(120))
    marketplace: Mapped[str] = mapped_column(String(2))
    notes: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[str] = mapped_column(String(40))


class MarketQuery(Base):
    __tablename__ = 'market_queries'
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    study_id: Mapped[str] = mapped_column(String(36), index=True)
    owner_id: Mapped[str] = mapped_column(String(36))
    request_id: Mapped[str] = mapped_column(String(36), unique=True)
    active_key: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    cache_key: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(20))
    section: Mapped[str] = mapped_column(String(24))
    tool: Mapped[str] = mapped_column(String(100))
    arguments: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), index=True)
    result: Mapped[str] = mapped_column(Text, default='{}')
    error: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))


def xiyou_key():
    path = Path(os.environ.get('SKILL_FORGE_DEPLOYMENT_ENV') or Path(__file__).resolve().parents[1] / '.env')
    return os.environ.get('XIYOU_MCP_TOKEN') or dotenv_values(path).get('XIYOU_MCP_TOKEN') or ''


class MarketClient(SellerSpriteClient):
    allowed_tools = frozenset(TOOLS.values())


class XiyouClient(SellerSpriteClient):
    endpoint = 'https://mcp.xydc.com/mcp'
    allowed_tools = frozenset(('search_market_insight_categories', 'get_account_credit_quota'))

    def __init__(self, key=None, transport=None):
        token = key if key is not None else xiyou_key()
        if not token:
            raise ResearchError('管理员尚未配置团队西柚 MCP。')
        super().__init__(token, transport)
        self.headers.pop('secret-key')
        self.headers['Authorization'] = 'Bearer ' + token

    def _post(self, *args, **kwargs):
        try:
            return super()._post(*args, **kwargs)
        except ResearchError as error:
            error.message = error.message.replace('卖家精灵', '西柚洞察')
            raise

    def call(self, name, arguments):
        try:
            value = super().call(name, arguments)
        except ResearchError as error:
            error.message = error.message.replace('卖家精灵', '西柚洞察')
            raise
        if not isinstance(value, dict) or value.get('status') != 200 or (isinstance(value.get('data'), dict) and value['data'].get('error')):
            raise ResearchError('西柚查询未完成，请检查站点、月份、权限和额度；未自动重试。')
        return value


class StudyInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=120)
    marketplace: str

    @field_validator('title')
    @classmethod
    def title_required(cls, value):
        if not value.strip(): raise ValueError('请填写调研名称。')
        return value.strip()

    @field_validator('marketplace')
    @classmethod
    def market_supported(cls, value):
        if value not in MARKETS: raise ValueError('请选择支持的站点。')
        return value


class QueryInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: UUID
    provider: Literal['sellersprite', 'xiyou'] = 'sellersprite'
    section: Literal['search', 'overview', 'history', 'distribution', 'products', 'brands']
    keyword: str = Field(default='', max_length=120)
    category_id: str = Field(default='', max_length=400, pattern=r'^[0-9:]*$')
    month: str = Field(default='', pattern=r'^(|\d{4}-(0[1-9]|1[0-2]))$')
    limit: Literal[1, 3, 5] = 3
    refresh: bool = False
    accept_cost: bool = False


class NotesInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    notes: str = Field(max_length=20000)


def query_arguments(study, body):
    if body.provider == 'xiyou':
        if body.section != 'search': raise HTTPException(422, '西柚第一版支持类目发现与市场概况，请使用搜索结果中的趋势与新品指标。')
        if not body.month: raise HTTPException(422, '西柚查询需要明确选择统计月份。')
        return 'search_market_insight_categories', {'country': study.marketplace, 'query': body.keyword.strip(),
            'cycleFilter': {'cycle': 'monthly', 'startDate': body.month + '-01'}, 'page': 1, 'pageSize': body.limit}
    args = {'marketplace': study.marketplace}
    if body.section == 'search':
        if not body.keyword.strip(): raise HTTPException(422, '请填写类目关键词。')
        return TOOLS['search'], {**args, 'keyword': body.keyword.strip(), 'page': {'cursor': 0, 'size': 20}}
    if not body.category_id: raise HTTPException(422, '请先在搜索结果中选择完整类目路径。')
    args['categoryId'] = body.category_id
    if body.section in ('overview', 'history'):
        if body.section == 'history' and body.month: raise HTTPException(422, '历史模块返回完整近24个月，不支持指定单月。')
        args.update(dataRange='LAST_24_MONTHS' if body.section == 'history' else 'LAST_30_DAYS', sampleCount=100)
        if body.month: args['currentMonth'] = int(body.month.replace('-', ''))
    else:
        if body.month: args['dataMonth'] = body.month.replace('-', '')
        if body.section == 'distribution': args.update(metrics=['price', 'ratingValue', 'ratingsCount', 'shelfTime'], topN=100)
        else: args.update(dimension='product' if body.section == 'products' else 'brand', topN=10)
    return TOOLS[body.section], args


def sanitize(value):
    """Persist data only; never provider credentials or diagnostic request headers."""
    if isinstance(value, dict):
        return {k: sanitize(v) for k, v in value.items() if not any(x in k.lower().replace('-', '_') for x in ('secret', 'token', 'authorization', 'api_key', 'headers'))}
    if isinstance(value, list): return [sanitize(x) for x in value]
    return value


def query_view(row, session=None):
    result = json.loads(row.result or '{}')
    if result.get('_following') and session is not None:
        source = session.get(MarketQuery, result['_following'])
        if source:
            return query_view(source, session) | {'id': row.id, 'study_id': row.study_id,
                'created_at': row.created_at, 'reused_from': source.id,
                'billing': {'chargedUnits': 0} if row.provider == 'sellersprite' else {'cost_credits': 0}}
    return {'id': row.id, 'study_id': row.study_id, 'provider': row.provider, 'section': row.section,
        'tool': row.tool, 'arguments': json.loads(row.arguments), 'status': row.status,
        'result': result, 'error': row.error, 'created_at': row.created_at, 'updated_at': row.updated_at,
        'reused_from': result.get('_reused_from'),
        'billing': ({'chargedUnits': 0} if row.provider == 'sellersprite' else {'cost_credits': 0}) if result.get('_reused_from') else
            result.get('billing') if row.provider == 'sellersprite' else {'cost_credits': result.get('cost_credits')}}


def study_view(row, user):
    return {key: getattr(row, key) for key in ('id', 'title', 'marketplace', 'author', 'owner_id', 'notes', 'created_at')} | {
        'can_edit': not user or row.owner_id == user['id'] or user.get('role') == 'admin'}


def process_market_one(engine, clients=None):
    with Session(engine) as session:
        row = session.scalar(select(MarketQuery).where(MarketQuery.status == 'queued').order_by(MarketQuery.created_at).limit(1))
        if row is None: return False
        identifier = row.id
        claimed = session.execute(update(MarketQuery).where(MarketQuery.id == identifier, MarketQuery.status == 'queued').values(status='running', updated_at=now()))
        session.commit()
        if claimed.rowcount != 1: return True
        provider, tool, arguments = row.provider, row.tool, json.loads(row.arguments)
    try:
        client_type = (clients or {'sellersprite': MarketClient, 'xiyou': XiyouClient})[provider]
        with client_type() as client:
            result = sanitize(client.call(tool, arguments))
        if not isinstance(result, dict): raise ResearchError('来源数据格式异常，请查看服务商状态后再决定是否刷新。', uncertain=True)
        status, error = 'succeeded', ''
    except ResearchError as exc:
        result, status, error = {}, 'unknown' if exc.uncertain else 'failed', exc.message
    except Exception:
        result, status, error = {}, 'unknown', '查询中断，结果及扣费待确认；不会自动重发。'
    with Session(engine) as session:
        row = session.get(MarketQuery, identifier)
        # Keep uncertain requests active to prevent accidental duplicate billing.
        row.status, row.result, row.error, row.updated_at = status, json.dumps(result, ensure_ascii=False), error, now()
        if status != 'unknown': row.active_key = None
        session.commit()
    return True


class MarketWorker:
    def __init__(self, engine):
        self.engine, self.stop_event = engine, threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True, name='market-insights')

    def start(self):
        # A process interrupted in-flight must never silently resubmit a paid query.
        with Session(self.engine) as session:
            session.execute(update(MarketQuery).where(MarketQuery.status == 'running').values(status='unknown',
                error='服务重启中断了查询，结果及扣费待确认；不会自动重发。', updated_at=now()))
            session.commit()
        self.thread.start()

    def run(self):
        while not self.stop_event.is_set():
            try: worked = process_market_one(self.engine)
            except Exception: worked = False
            self.stop_event.wait(.5 if worked else 2)

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=2)


def build_market_router(engine):
    router = APIRouter(prefix='/api/market-insights', tags=['market-insights'])

    def require_engine():
        if engine is None: raise HTTPException(503, '市场洞察需要数据库。')

    def get_study(session, identifier):
        row = session.get(MarketStudy, str(identifier))
        if row is None: raise HTTPException(404, '调研项目不存在。')
        return row

    @router.get('/services')
    def services():
        return {'sellersprite': bool(shared_key()), 'xiyou': bool(xiyou_key()), 'shared': True}

    @router.get('/studies')
    def studies(request: Request):
        require_engine()
        with Session(engine) as session:
            return [study_view(row, request.state.user) for row in session.scalars(select(MarketStudy).order_by(MarketStudy.created_at.desc()))]

    @router.post('/studies', status_code=201)
    def create(body: StudyInput, request: Request):
        require_engine()
        user = request.state.user or {'id': 'local', 'display_name': '本地用户'}
        with Session(engine) as session:
            row = MarketStudy(id=str(uuid4()), owner_id=user['id'], author=user.get('display_name') or user.get('username', ''),
                title=body.title, marketplace=body.marketplace, notes='', created_at=now())
            session.add(row); session.commit()
            return study_view(row, user)

    @router.get('/studies/{identifier}')
    def detail(identifier: UUID, request: Request):
        require_engine()
        with Session(engine) as session:
            row = get_study(session, identifier)
            return study_view(row, request.state.user) | {'queries': [query_view(q, session) for q in session.scalars(
                select(MarketQuery).where(MarketQuery.study_id == row.id).order_by(MarketQuery.created_at.desc()))]}

    @router.put('/studies/{identifier}/notes')
    def notes(identifier: UUID, body: NotesInput, request: Request):
        require_engine()
        with Session(engine) as session:
            row = get_study(session, identifier)
            if not study_view(row, request.state.user)['can_edit']: raise HTTPException(403, '只有作者和管理员可修改调研笔记。')
            row.notes = body.notes; session.commit()
            return study_view(row, request.state.user)

    @router.post('/studies/{identifier}/queries')
    def submit(identifier: UUID, body: QueryInput, request: Request):
        require_engine()
        with Session(engine) as session:
            study = get_study(session, identifier)
            if not body.accept_cost: raise HTTPException(422, '请先确认查询范围及额度消耗。')
            tool, arguments = query_arguments(study, body)
            key = hashlib.sha256(json.dumps([body.provider, tool, arguments], sort_keys=True).encode()).hexdigest()
            existing = session.scalar(select(MarketQuery).where(MarketQuery.request_id == str(body.request_id)))
            if existing:
                if existing.study_id != study.id or existing.cache_key != key: raise HTTPException(409, '请求编号已用于其他查询。')
                return query_view(existing, session) | {'cache_hit': True}
            active = session.scalar(select(MarketQuery).where(MarketQuery.active_key == key))
            if active:
                if active.study_id == study.id: return query_view(active, session) | {'cache_hit': True}
                row = MarketQuery(id=str(uuid4()), study_id=study.id, owner_id=(request.state.user or {}).get('id', 'local'),
                    request_id=str(body.request_id), active_key=None, cache_key=key, provider=body.provider,
                    section=body.section, tool=tool, arguments=json.dumps(arguments), status='linked',
                    result=json.dumps({'_following': active.id}), error='', created_at=now(), updated_at=now())
                session.add(row); session.commit()
                return query_view(row, session) | {'cache_hit': True}
            if not body.refresh:
                cached = session.scalar(select(MarketQuery).where(MarketQuery.cache_key == key, MarketQuery.status == 'succeeded').order_by(MarketQuery.created_at.desc()).limit(1))
                if cached:
                    row = MarketQuery(id=str(uuid4()), study_id=study.id, owner_id=(request.state.user or {}).get('id', 'local'),
                        request_id=str(body.request_id), active_key=None, cache_key=key, provider=body.provider, section=body.section,
                        tool=tool, arguments=json.dumps(arguments), status='succeeded',
                        result=json.dumps(json.loads(cached.result) | {'_reused_from': cached.id}),
                        error='', created_at=now(), updated_at=cached.updated_at)
                    session.add(row); session.commit()
                    return query_view(row) | {'cache_hit': True, 'reused_from': cached.id}
            if not (shared_key() if body.provider == 'sellersprite' else xiyou_key()): raise HTTPException(409, '团队公共 MCP 尚未配置，请联系管理员。')
            row = MarketQuery(id=str(uuid4()), study_id=study.id, owner_id=(request.state.user or {}).get('id', 'local'),
                request_id=str(body.request_id), active_key=key, cache_key=key, provider=body.provider, section=body.section,
                tool=tool, arguments=json.dumps(arguments), status='queued', result='{}', error='', created_at=now(), updated_at=now())
            session.add(row)
            try: session.commit()
            except IntegrityError:
                session.rollback()
                active = session.scalar(select(MarketQuery).where((MarketQuery.active_key == key) | (MarketQuery.request_id == str(body.request_id))))
                if active: return query_view(active) | {'cache_hit': True}
                raise
            return query_view(row) | {'cache_hit': False}

    @router.get('/queries/{identifier}')
    def query(identifier: UUID):
        require_engine()
        with Session(engine) as session:
            row = session.get(MarketQuery, str(identifier))
            if row is None: raise HTTPException(404, '查询记录不存在。')
            return query_view(row, session)

    @router.post('/queries/{identifier}/resolve')
    def resolve(identifier: UUID, request: Request):
        require_engine()
        with Session(engine) as session:
            row = session.get(MarketQuery, str(identifier))
            if row is None: raise HTTPException(404, '查询记录不存在。')
            linked = json.loads(row.result or '{}').get('_following')
            if linked: row = session.get(MarketQuery, linked)
            user = request.state.user
            if user and user['id'] != row.owner_id and user.get('role') != 'admin': raise HTTPException(403, '只有发起人或管理员可解除待确认状态。')
            if row.status != 'unknown': raise HTTPException(409, '仅结果待确认的查询需要人工核对。')
            row.active_key = None; row.status = 'failed'; row.updated_at = now()
            row.error = '已人工确认服务商状态；可显式刷新，原记录保留。'
            session.commit()
            return query_view(row)

    return router
