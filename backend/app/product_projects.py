"""Project API: two explicit approval gates, optimistic edits and immutable history."""
import json
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.authorization import principal
from app.database import ProductImageProject, SkillPackage, SkillVersion
from app.image_jobs import now, view as job_view
from app.database import ImageJob
from app.project_materials import MAX_ASSETS, asset_root, prepare_asset, project_root
from app.project_schemas import ArtifactUpdate, Command, OutputReview, ProjectInput, validate_plan, validate_points

BUSY = {'queued', 'running', 'generating'}


def decode(row):
    return json.loads(row.state)


def save(row, state):
    row.state = json.dumps(state, ensure_ascii=False)
    row.revision += 1
    row.updated_at = now()


def event(state, kind, **values):
    state['history'].append({'at': now(), 'kind': kind, **values})


def message(state, role, content):
    item = {'id': str(uuid4()), 'role': role, 'content': content, 'at': now()}
    state['messages'].append(item)
    return item


def invalidate(state, points=False):
    if points:
        state['points_approval'] = None
        state['approved_point_ids'] = []
    state['plan_approval'] = None


def project_view(row, session=None):
    state = decode(row)
    outputs = state.get('outputs', [])
    if session:
        for output in outputs:
            job = session.get(ImageJob, output.get('job_id', ''))
            if job:
                output['job'] = job_view(job).model_dump()
    return {'id': row.id, 'title': row.title, 'revision': row.revision, 'status': row.status,
            'action': row.action, 'created_at': row.created_at, 'updated_at': row.updated_at, **state}


def owned(session, identifier, owner, lock=False):
    row = session.get(ProductImageProject, str(identifier), with_for_update=lock)
    if row is None or row.owner_id != owner:
        raise HTTPException(404, '商品图项目不存在。')
    return row


def editable(row, revision):
    if row.revision != revision:
        raise HTTPException(409, '项目已更新，请等待刷新后重新操作。')
    if row.status in BUSY:
        raise HTTPException(409, '正在处理当前步骤，请完成或取消后修改。')


def skill_snapshot(session, identifier, owner):
    package = session.get(SkillPackage, str(identifier))
    if not package or not package.current_version_id or (package.source != 'builtin' and package.owner_id != (principal.get() or {}).get('id')):
        raise HTTPException(422, '请选择已启用的内置技能或自己的技能。')
    version = session.get(SkillVersion, package.current_version_id)
    if not version or version.status != 'ready':
        raise HTTPException(422, '技能版本尚未就绪。')
    return {'id': package.id, 'name': package.name, 'version_id': version.id, 'version_label': version.version_label}


def connection_scope(configs, owner, config_id):
    profile = configs.snapshot(owner, config_id)
    text_url, _, _ = configs.resolve_text(owner)
    vision_url, _, _ = configs.resolve_vision(owner)
    return profile, {'image': profile['base_url'], 'text': text_url, 'vision': vision_url}


def check_scope(configs, owner, state):
    profile, receivers = connection_scope(configs, owner, state['config_id'])
    authorization = state.get('authorization')
    if not authorization or authorization['receivers'] != receivers:
        raise HTTPException(409, '资料接收方已改变，请重新授权并分析资料。')
    if authorization['assets'] != {a['id']: a['sha256'] for a in state['assets']}:
        raise HTTPException(409, '资料范围已改变，请重新授权并分析资料。')
    return profile


def build_project_router(engine, directory, configs):
    router = APIRouter(prefix='/api/product-projects', tags=['product-projects'])

    def database():
        if engine is None:
            raise HTTPException(503, '请先配置数据库并执行迁移。')

    @router.get('')
    def list_projects(request: Request):
        database()
        with Session(engine) as session:
            rows = session.scalars(select(ProductImageProject).where(ProductImageProject.owner_id == request.state.image_owner).order_by(ProductImageProject.updated_at.desc()))
            return [{'id': r.id, 'title': r.title, 'status': r.status, 'updated_at': r.updated_at} for r in rows]

    @router.post('', status_code=201)
    def create_project(request: Request, data: ProjectInput):
        database()
        current = configs.get(request.state.image_owner)
        if not current or current['id'] != str(data.config_id) or data.image_model_name not in current['model_names']:
            raise HTTPException(422, '请选择已保存的生图模型。')
        if not data.image_model_name.startswith('gpt-image-'):
            raise HTTPException(422, '原始 imagegen 脚本仅支持 gpt-image-* 模型。')
        with Session(engine) as session, session.begin():
            skill = skill_snapshot(session, data.skill_id, request.state.image_owner)
            state = {'sku': data.sku, 'brief': data.brief, 'skill': skill, 'config_id': str(data.config_id),
                     'image_model_name': data.image_model_name, 'image_count': data.image_count,
                     'assets': [], 'messages': [], 'history': [], 'versions': [], 'outputs': [],
                     'points': None, 'plan': None, 'points_version': 0, 'plan_version': 0,
                     'plan_points_version': 0,
                     'points_approval': None, 'plan_approval': None, 'approved_point_ids': [],
                     'authorization': None, 'error': ''}
            event(state, 'created', skill=skill, image_model_name=data.image_model_name)
            row = ProductImageProject(id=str(uuid4()), title=data.title, owner_id=request.state.image_owner,
                revision=1, status='draft', action='', state=json.dumps(state, ensure_ascii=False), created_at=now(), updated_at=now())
            session.add(row)
            return project_view(row)

    @router.get('/{identifier}')
    def get_project(request: Request, identifier: UUID):
        database()
        with Session(engine) as session:
            return project_view(owned(session, identifier, request.state.image_owner), session)

    @router.post('/{identifier}/assets')
    def upload(request: Request, identifier: UUID, revision: Annotated[int, Form()], asset_id: Annotated[UUID, Form()],
               role: Annotated[Literal['manual', 'specification', 'product_identity', 'owned_artwork', 'approved_copy'], Form()],
               file: Annotated[UploadFile, File()]):
        database()
        # Validate ownership before parsing or writing any files.
        with Session(engine) as session:
            row = owned(session, identifier, request.state.image_owner)
            prior = next((a for a in decode(row)['assets'] if a['id'] == str(asset_id)), None)
            if not prior:
                editable(row, revision)
        content = file.file.read(20 * 1024 * 1024 + 1)
        asset, files = prepare_asset(content, file.filename, role, str(asset_id))
        with Session(engine) as session, session.begin():
            row = owned(session, identifier, request.state.image_owner, True)
            state = decode(row)
            prior = next((a for a in state['assets'] if a['id'] == asset['id']), None)
            if prior:
                if (prior['sha256'], prior['role']) != (asset['sha256'], asset['role']):
                    raise HTTPException(409, '此上传标识已用于其他资料。')
                return project_view(row)
            editable(row, revision)
            if len(state['assets']) >= MAX_ASSETS or sum(len(a.get('pages', [])) for a in state['assets']) + len(asset.get('pages', [])) > 80:
                raise HTTPException(422, '每个项目最多 24 份资料、合计 80 页 PDF。')
            root = asset_root(directory, str(identifier), str(asset_id))
            root.mkdir(parents=True, exist_ok=True)
            for name, value in files.items():
                path = root / name
                if path.exists():
                    if path.read_bytes() != value:
                        raise HTTPException(409, '资料文件已存在且内容不同，未覆盖。')
                else:
                    path.write_bytes(value)
            state['assets'].append(asset)
            invalidate(state, points=True)
            state['authorization'] = None
            row.status, row.action = 'draft', ''
            event(state, 'asset_added', asset_id=asset['id'], role=role, sha256=asset['sha256'])
            save(row, state)
            return project_view(row)

    @router.delete('/{identifier}/assets/{asset_id}')
    def remove_asset(request: Request, identifier: UUID, asset_id: UUID, revision: int):
        database()
        with Session(engine) as session, session.begin():
            row = owned(session, identifier, request.state.image_owner, True)
            editable(row, revision)
            state = decode(row)
            if not any(a['id'] == str(asset_id) for a in state['assets']):
                raise HTTPException(404, '资料不存在。')
            # Retain immutable originals for older approvals and output versions.
            state.setdefault('retired_assets', []).extend(a for a in state['assets'] if a['id'] == str(asset_id))
            state['assets'] = [a for a in state['assets'] if a['id'] != str(asset_id)]
            invalidate(state, points=True)
            state['authorization'], state['points'], state['plan'] = None, None, None
            row.status = 'draft'
            event(state, 'asset_removed', asset_id=str(asset_id))
            save(row, state)
            return project_view(row)

    @router.get('/{identifier}/assets/{asset_id}/{kind}')
    def get_asset(request: Request, identifier: UUID, asset_id: UUID, kind: Literal['original', 'preview']):
        database()
        with Session(engine) as session:
            state = decode(owned(session, identifier, request.state.image_owner))
            asset = next((a for a in state['assets'] + state.get('retired_assets', []) if a['id'] == str(asset_id)), None)
            if not asset:
                raise HTTPException(404, '资料不存在。')
            name = 'preview.jpg' if kind == 'preview' else ('original.pdf' if asset['kind'] == 'pdf' else 'original.bin')
            path = asset_root(directory, str(identifier), str(asset_id)) / name
            if not path.is_file():
                raise HTTPException(404, '文件不存在。')
            return FileResponse(path, media_type='image/jpeg' if kind == 'preview' else 'application/octet-stream',
                filename=asset['name'] if kind == 'original' else None, headers={'X-Content-Type-Options': 'nosniff'})

    @router.put('/{identifier}/artifacts')
    def update_artifacts(request: Request, identifier: UUID, data: ArtifactUpdate):
        database()
        with Session(engine) as session, session.begin():
            row = owned(session, identifier, request.state.image_owner, True)
            editable(row, data.revision)
            state = decode(row)
            try:
                if (data.points is None) == (data.plan is None):
                    raise ValueError('每次只修改卖点或图需中的一项。')
                if data.points:
                    validate_points(data.points, state)
                    state['points'] = data.points.model_dump()
                    state['points_version'] += 1
                    invalidate(state, points=True)
                    row.status = 'waiting_points'
                else:
                    if state['points_approval'] != state['points_version']:
                        raise ValueError('请先确认当前卖点版本。')
                    validate_plan(data.plan, state)
                    state['plan'] = data.plan.model_dump(by_alias=True)
                    state['plan_version'] += 1
                    state['plan_points_version'] = state['points_version']
                    invalidate(state)
                    row.status = 'waiting_plan'
            except ValueError as error:
                raise HTTPException(422, str(error)) from None
            event(state, 'manual_edit', artifact='points' if data.points else 'plan')
            state['versions'].append({'at': now(), 'points_version': state['points_version'], 'plan_version': state['plan_version'],
                                      'points': state['points'], 'plan': state['plan']})
            save(row, state)
            return project_view(row)

    @router.post('/{identifier}/commands')
    def command(request: Request, identifier: UUID, data: Command):
        database()
        with Session(engine) as session, session.begin():
            row = owned(session, identifier, request.state.image_owner, True)
            if data.action == 'cancel':
                if row.revision != data.revision:
                    raise HTTPException(409, '项目已更新，请刷新后操作。')
                state = decode(row)
                row.status, row.action, row.lease_until = 'cancelled', '', None
                # Already sent image requests must still be reconciled, never re-ordered.
                event(state, 'cancelled', note='已提交图片继续保留；不会提交后续图。')
                save(row, state)
                return project_view(row, session)
            editable(row, data.revision)
            state = decode(row)
            action = data.action
            if action == 'analyze':
                if not data.authorized:
                    raise HTTPException(422, '请确认资料权利及向当前服务商上传分析和制图的授权。')
                if not any(a['role'] == 'product_identity' for a in state['assets']):
                    raise HTTPException(422, '请至少上传一张产品身份参考图。')
                _, receivers = connection_scope(configs, request.state.image_owner, state['config_id'])
                state['authorization'] = {'at': now(), 'receivers': receivers,
                    'assets': {a['id']: a['sha256'] for a in state['assets']},
                    'purpose': '本项目资料理解、卖点与图需规划、参考编辑及质检',
                    'statement': '我拥有这些资料的使用权，授权将本项目资料发给显示的服务商，用于分析、制图和质检。'}
                invalidate(state, points=True)
            elif action == 'approve_points':
                if not state['points'] or not data.point_ids or len(set(data.point_ids)) != len(data.point_ids):
                    raise HTTPException(422, '请选择需要确认的卖点。')
                points = {p['id']: p for p in state['points']['points']}
                if any(i not in points or points[i]['status'] != 'supported' or points[i]['priority'] == 'excluded' for i in data.point_ids):
                    raise HTTPException(422, '仅有资料支持且未排除的卖点可进入制作，请先补证或收窄表述。')
                state['approved_point_ids'] = data.point_ids
                state['points_approval'] = state['points_version']
                state['plan_approval'] = None
                row.status, row.action = 'waiting_plan', ''
                event(state, 'points_approved', version=state['points_version'], point_ids=data.point_ids)
                save(row, state)
                return project_view(row)
            elif action in ('plan', 'discuss_plan', 'generate'):
                if not state['points_approval'] or state['points_approval'] != state['points_version']:
                    raise HTTPException(409, '请先确认当前卖点版本。')
                if action in ('discuss_plan', 'generate') and not state['plan']:
                    raise HTTPException(409, '请先规划图片图需。')
                if action == 'generate':
                    if state.get('plan_points_version') != state['points_version']:
                        raise HTTPException(409, '卖点版本已变化，请重新规划或保存复核后的图需。')
                    profile = check_scope(configs, request.state.image_owner, state)
                    if state['image_model_name'] != profile['model'] or not profile['generation_verified'] or not profile['edit_verified']:
                        raise HTTPException(409, '请在模型配置中将本项目模型设为默认，并完成该模型的生成与参考编辑验证后开始制作。')
                    try:
                        from app.project_schemas import PlanArtifact
                        validate_plan(PlanArtifact.model_validate(state['plan']), state)
                    except ValueError as error:
                        raise HTTPException(422, str(error)) from None
                    if any(o['plan_version'] == state['plan_version'] for o in state['outputs']):
                        raise HTTPException(409, '当前图需已有制作记录，请恢复核对现有任务或修改图需形成新版本。')
                    state['plan_approval'] = state['plan_version']
                    state['generation_id'] = str(uuid4())
                    state['authorization']['generation_approved_at'] = now()
                    event(state, 'plan_approved', version=state['plan_version'], model=state['image_model_name'], count=len(state['plan']['shots']))
            elif action == 'discuss_points':
                if not state['points']:
                    raise HTTPException(409, '请先分析资料并提炼卖点。')
            elif action == 'resume':
                action = state.get('interrupted_action') or ''
                if action != 'generate':
                    raise HTTPException(409, '策划步骤中断后，请重新发起资料分析或讨论；不会自动重复请求。')
                if state['plan_approval'] != state['plan_version']:
                    raise HTTPException(409, '图需已变化，需要重新确认。')
            if action != 'analyze':
                check_scope(configs, request.state.image_owner, state)
            if data.message.strip():
                message(state, 'user', data.message.strip())
            if action.startswith('discuss') and not data.message.strip():
                raise HTTPException(422, '请填写讨论或修改要求。')
            state['error'] = ''
            state['pending_message'] = data.message
            if action.startswith('discuss'):
                state['discussion_return_status'] = row.status
            row.status, row.action = 'queued', action
            event(state, 'command', action=action)
            save(row, state)
            return project_view(row)

    @router.get('/{identifier}/outputs/{output_id}/prompt')
    def prompt(request: Request, identifier: UUID, output_id: UUID):
        database()
        with Session(engine) as session:
            state = decode(owned(session, identifier, request.state.image_owner))
            if not any(o['id'] == str(output_id) for o in state['outputs']):
                raise HTTPException(404, '提示词不存在。')
        path = project_root(directory, str(identifier)) / 'prompts' / f'{output_id}.txt'
        if not path.is_file():
            raise HTTPException(404, '提示词尚未编写。')
        return FileResponse(path, media_type='text/plain; charset=utf-8')

    @router.post('/{identifier}/outputs/{output_id}/review')
    def review(request: Request, identifier: UUID, output_id: UUID, data: OutputReview):
        database()
        with Session(engine) as session, session.begin():
            row = owned(session, identifier, request.state.image_owner, True)
            editable(row, data.revision)
            state = decode(row)
            output = next((o for o in state['outputs'] if o['id'] == str(output_id)), None)
            job = session.get(ImageJob, output['job_id']) if output and output.get('job_id') else None
            if not output or not job or job.status != 'succeeded':
                raise HTTPException(422, '仅可验收已成功生成的图片。')
            output['human_review'], output['human_notes'] = data.status, data.notes
            if row.status in ('review', 'completed'):
                latest = [o for o in state['outputs'] if o['plan_version'] == state['plan_version']]
                row.status = 'completed' if len(latest) == state['image_count'] and all(o['human_review'] == 'passed' for o in latest) else 'review'
            event(state, 'human_review', output_id=str(output_id), status=data.status, notes=data.notes)
            save(row, state)
            return project_view(row, session)

    return router
