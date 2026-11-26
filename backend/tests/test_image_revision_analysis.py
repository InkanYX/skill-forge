import json
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.database import ImageJob
from app.image_jobs import artifact
from app.standard_image_worker import process_standard_one
from app.image_provider import GenerationError
from test_creation_skills import workflow, submit
from test_standard_images import standard, fake_executor
from test_image_jobs import png


def attach_original_materials(workflow, source_id):
    import hashlib
    import io
    import pypdfium2 as pdfium
    from app.database import CreationProject, CreationMaterial
    from app.creation_materials import material_path
    _, _, engine, directory, *_ = workflow
    project_id = str(uuid4())
    with pdfium.PdfDocument.new() as doc:
        doc.new_page(300, 200)
        output = io.BytesIO()
        doc.save(output)
    with Session(engine) as session, session.begin():
        source = session.get(ImageJob, source_id)
        session.add(CreationProject(id=project_id, title='Original product', kind='plan',
            owner_id=source.owner_id, content='{}', created_at='now', updated_at='now'))
        profile = json.loads(source.execution_profile)
        profile['creation_project_id'] = project_id
        profile['source_documents'] = {}
        source.execution_profile = json.dumps(profile)
        for name, kind, mime, content in [('manual.pdf', '说明书', 'application/pdf', output.getvalue()),
                ('photo.png', '产品实拍', 'image/png', png())]:
            mid = str(uuid4())
            path = material_path(directory, project_id, mid)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            session.add(CreationMaterial(id=mid, project_id=project_id, name=name, kind=kind,
                media_type=mime, digest=hashlib.sha256(content).hexdigest(), size=len(content), pages=1, created_at='now'))
    return project_id


def revised(workflow, instruction='右侧支撑杆画多了，只修正这一处'):
    first,_=submit(workflow,reference=png())
    assert process_standard_one(workflow[1],fake_executor)
    images,_=submit(workflow,prompt=instruction,source_job_id=first[0]['id'])
    return first[0],images[0]


def setup_planners(monkeypatch, events, *, vision_failure=False, needs_input=False, prompt=None):
    intent={'status':'ready','user_issue':'右侧支撑杆疑似多出，需要与参考核对',
        'requested_changes':['只修正右侧支撑杆'],'preserve':['其他结构、背景和文案']}
    def chat(*args,**kwargs):
        events.append('understand')
        return {'content':json.dumps(intent)}
    def vision(*args,**kwargs):
        events.append('inspect')
        if vision_failure:
            from app.agent_runtime import AgentError
            raise AgentError('视觉接口返回403',diagnostic={'http_status':403})
        assert args[3] == png() and kwargs['reference'] is None
        return '右侧疑似出现重复支撑杆，身份参考未能证明隐藏连接；仅处理用户指定区域。'
    def plan(engine,storage,directory,snapshot,instructions,brief,provider,**kwargs):
        events.append('plan')
        assert brief['revision_context']['user_instruction'] == '右侧支撑杆画多了，只修正这一处'
        assert '疑似' in brief['reference_observations']
        (directory/'skill-context.md').write_text('mocked skill context',encoding='utf-8')
        if needs_input:
            return json.dumps({'status':'needs_input','explanation':'请提供右侧连接的清晰参考图'}),{}
        return json.dumps({**intent,'observed_issues':['右侧疑似重复支撑杆'],
            'correction_steps':['仅移除右侧误画的额外支撑杆，保留正确连接'],
            'uncertainties':['隐藏连接不可确认，不修改'],
            'prompt':prompt or 'Edit only the extra right support visible in the artwork. Preserve all other product geometry, background, verified text and framing.\nOutput: PNG.'}),{'used_skills':[],'files':[]}
    monkeypatch.setattr('app.agent_runtime._chat',chat)
    monkeypatch.setattr('app.agent_runtime._vision',vision)
    monkeypatch.setattr('app.skill_agent.plan_with_skills',plan)


def test_understand_then_inspect_then_plan_then_edit_actual_source(workflow,monkeypatch):
    client,store,engine,directory,*_=workflow
    source,target=revised(workflow)
    events=[];setup_planners(monkeypatch,events)
    def execute(folder,profile,key,prompt,reference):
        events.append('edit')
        assert reference == artifact(directory,source['id'],'result.png').read_bytes()
        assert prompt.startswith('Edit only') and 'extra right support' in prompt
        assert profile['revision_prepared'] is True
        return fake_executor(folder,profile,key,prompt,reference)
    assert process_standard_one(store,execute,reviewer=lambda *args,**kwargs:{'status':'uncertain','summary':'待审核','checks':[]})
    assert events == ['understand','inspect','plan','edit']
    value=client.get('/api/image-jobs/'+target['id']).json()
    assert value['status']=='succeeded'
    record=value['execution_result']['revision_analysis']
    assert record['stage']=='ready' and record['plan']['uncertainties']
    assert artifact(directory,source['id'],'result.png').is_file()
    assert artifact(directory,target['id'],'prompt.txt').read_text(encoding='utf-8') == value['prompt']


@pytest.mark.parametrize('prompt,reason',[
    ('Edit only [specific structural area]. Output: PNG.','未填写的占位内容'),
    ('Edit only the support. Completely redesign the product. Output: PNG.','从头重画或完全重新设计'),
    ('Edit only the support. Replace the background. Preserve the background exactly. Output: PNG.','同时要求修改并保留'),
    ('Fix the support. Output: PNG.','必须以 Edit only 开始'),
])
def test_rejected_prompt_preserves_plan_draft_and_specific_checks(workflow,monkeypatch,prompt,reason):
    client,store,engine,directory,*_=workflow
    _,target=revised(workflow)
    setup_planners(monkeypatch,[],prompt=prompt)
    assert process_standard_one(store,lambda *args:pytest.fail('rejected prompt must not call images'))
    value=client.get('/api/image-jobs/'+target['id']).json()
    assert value['status']=='failed' and reason in value['message']
    record=value['execution_result']['revision_analysis']
    assert record['plan']['prompt']==prompt
    assert any(reason in check['message'] for check in record['prompt_checks'])
    assert artifact(directory,target['id'],'revision-prompt-draft.txt').read_text(encoding='utf-8')==prompt
    reply=json.loads(artifact(directory,target['id'],'revision-planning-response.txt').read_text(encoding='utf-8'))
    assert reply['prompt']==prompt
    assert artifact(directory,target['id'],'skill-workflow.json').is_file()
    assert not artifact(directory,target['id'],'prompt.txt').exists()


def test_negative_redesign_instructions_reach_edit_with_actual_reference(workflow,monkeypatch):
    client,store,engine,directory,*_=workflow
    source,target=revised(workflow)
    prompt='Edit only the height button. Do not recreate from scratch. Do not replace the background. Preserve the background exactly.\nOutput: PNG.'
    setup_planners(monkeypatch,[],prompt=prompt)
    def execute(folder,profile,key,actual_prompt,reference):
        assert reference==artifact(directory,source['id'],'result.png').read_bytes()
        assert actual_prompt==prompt
        return fake_executor(folder,profile,key,actual_prompt,reference)
    assert process_standard_one(store,execute,reviewer=lambda *args,**kwargs:{'status':'uncertain','summary':'待审核','checks':[]})
    assert client.get('/api/image-jobs/'+target['id']).json()['status']=='succeeded'


@pytest.mark.parametrize('failure',['vision','needs_input','missing_vision','malformed_intent'])
def test_analysis_failure_never_calls_image_model(workflow,monkeypatch,failure):
    client,store,engine,directory,*_=workflow
    _,target=revised(workflow)
    events=[];setup_planners(monkeypatch,events,vision_failure=failure=='vision',needs_input=failure=='needs_input')
    if failure=='missing_vision':
        from fastapi import HTTPException
        monkeypatch.setattr(store,'resolve_vision',lambda *args,**kwargs:(_ for _ in ()).throw(HTTPException(422,'请配置视觉模型')))
    if failure=='malformed_intent':
        monkeypatch.setattr('app.agent_runtime._chat',lambda *args,**kwargs:{'content':'invalid JSON'})
    assert process_standard_one(store,lambda *args:pytest.fail('analysis failure must not spend on images'))
    value=client.get('/api/image-jobs/'+target['id']).json()
    assert value['status']=='failed',value
    assert value['execution_result']['revision_analysis']['stage']=='failed'
    assert not artifact(directory,target['id'],'result.png').exists()
    if failure=='needs_input':assert '清晰参考图' in value['message']


def test_failed_image_retry_reuses_finished_analysis_and_exact_prompt(workflow,monkeypatch):
    client,store,engine,directory,*_=workflow
    _,target=revised(workflow)
    events=[];setup_planners(monkeypatch,events)
    def fail(*args):raise GenerationError('temporary failure',diagnostic={'http_status':500})
    assert process_standard_one(store,fail)
    original=client.get('/api/image-jobs/'+target['id']).json()
    response=client.post('/api/image-jobs/'+target['id']+'/retry',files={'request_id':(None,str(uuid4()))})
    assert response.status_code==202,response.text
    created=response.json()
    assert events==['understand','inspect','plan']
    assert process_standard_one(store,fake_executor,reviewer=lambda *args,**kwargs:{'status':'uncertain','summary':'待审核','checks':[]})
    current=client.get('/api/image-jobs/'+created['id']).json()
    assert current['status']=='succeeded' and current['prompt']==original['prompt']
    analysis=current['execution_result']['revision_analysis']
    assert analysis == {**original['execution_result']['revision_analysis'],
        'reused_preparation':True,'retry_source_job_id':target['id']}
    assert events==['understand','inspect','plan']


def test_prepared_agent_flag_cannot_bypass_revision_analysis(workflow,monkeypatch):
    client,store,engine,directory,*_=workflow
    _,target=revised(workflow)
    with Session(engine) as session,session.begin():
        row=session.get(ImageJob,target['id'])
        profile=json.loads(row.execution_profile)
        profile['prepared_by_agent']=True
        row.execution_profile=json.dumps(profile)
    events=[];setup_planners(monkeypatch,events)
    assert process_standard_one(store,fake_executor,reviewer=lambda *args,**kwargs:{'status':'uncertain','summary':'待审核','checks':[]})
    assert events==['understand','inspect','plan']
    assert client.get('/api/image-jobs/'+target['id']).json()['status']=='succeeded'


@pytest.mark.parametrize('inspect_originals', [True, False])
def test_revision_reads_uploaded_pdf_and_photo_before_verdict(workflow, monkeypatch, inspect_originals):
    client, store, engine, directory, *_ = workflow
    source, target = revised(workflow)
    project_id = attach_original_materials(workflow, source['id'])
    events = []; setup_planners(monkeypatch, events)
    original_plan = __import__('app.skill_agent', fromlist=['plan_with_skills']).plan_with_skills
    def vision(*args, **kwargs):
        # Actual source still goes to inspection; each original goes to vision separately as JPEG.
        if args[3].startswith(b'\xff\xd8'):
            return '原始资料显示按钮位于伸缩杆接合处，来源为当前文件和页码。'
        return '右侧疑似多出支撑杆，需检查原始说明书。'
    def plan(*args, **kwargs):
        materials = args[5]['materials']
        assert {item['name'] for item in materials} == {'manual.pdf', 'photo.png'}
        tools = {tool.name: tool for tool in kwargs['extra_tools']}
        if inspect_originals:
            for item in materials:
                if item['media_type'] == 'application/pdf':
                    # A scanned PDF's empty text layer must not count as verified evidence.
                    tools['read_material'].invoke({'material_id':item['id'],'page':1})
                command = tools['view_material'].invoke({'name':'view_material','args':{'material_id':item['id'],'page':1},'id':item['id'],'type':'tool_call'})
                assert len(command.update['messages']) == 1
                assert '伸缩杆' in command.update['messages'][0].content
        return original_plan(*args, **kwargs)
    monkeypatch.setattr('app.agent_runtime._vision', vision)
    monkeypatch.setattr('app.skill_agent.plan_with_skills', plan)
    executor = fake_executor if inspect_originals else lambda *args: pytest.fail('unchecked evidence must not reach image model')
    assert process_standard_one(store, executor, reviewer=lambda *args,**kwargs:{'status':'uncertain','summary':'待审核','checks':[]})
    value = client.get('/api/image-jobs/'+target['id']).json()
    assert value['status'] == ('succeeded' if inspect_originals else 'failed'), value
    record = value['execution_result']['revision_analysis']
    assert record['material_project_id'] == project_id
    if inspect_originals:
        assert len(record['material_reads']) == 3
        assert len(json.loads(artifact(directory,target['id'],'material-read-log.json').read_text(encoding='utf-8'))) == 3
    else:
        assert '尚未实际核对' in value['message']


def test_original_material_lineage_survives_chained_edits_and_rejects_other_owner(workflow, monkeypatch):
    from app.revision_materials import revision_materials
    from app.database import CreationProject, AgentRun
    _, store, engine, directory, *_ = workflow
    source, target = revised(workflow)
    project_id = attach_original_materials(workflow, source['id'])
    # Historical revisions without copied project IDs still resolve through parents.
    assert revision_materials(engine, target['id'])[0] == project_id
    with Session(engine) as session, session.begin():
        row = session.get(ImageJob,target['id'])
        profile = json.loads(row.execution_profile)
        profile.update(creation_project_id=project_id, source_documents={})
        row.execution_profile = json.dumps(profile)
        row.status = 'succeeded'
        session.get(AgentRun,row.agent_run_id).status = 'succeeded'
    artifact(directory,target['id'],'result.png').write_bytes(png())
    newer, _ = submit(workflow,prompt='再核对连接结构',source_job_id=target['id'])
    with Session(engine) as session:
        profile = json.loads(session.get(ImageJob,newer[0]['id']).execution_profile)
        assert profile['creation_project_id'] == project_id
        assert profile['source_documents'] == {}
    with Session(engine) as session, session.begin():
        session.get(CreationProject,project_id).owner_id = 'another-account'
    with pytest.raises(GenerationError, match='归属'):
        revision_materials(engine,target['id'])


@pytest.mark.parametrize('verdict',['ready','needs_input','unread'])
def test_height_question_is_deferred_until_original_evidence_is_checked(workflow,monkeypatch,verdict):
    client,store,engine,directory,*_=workflow
    source,target=revised(workflow,'立柱太矮了，尺寸不对')
    attach_original_materials(workflow,source['id'])
    with Session(engine) as session,session.begin():
        row=session.get(ImageJob,target['id'])
        profile=json.loads(row.execution_profile)
        profile['revision_context']['source_prompt']='Preserve the existing height and proportions. Edit only the height button.'
        row.execution_profile=json.dumps(profile)
    events=[]
    def chat(url,key,model,messages,**kwargs):
        events.append('understand')
        # The first decision sees the current request, not historical prompt locks.
        brief=json.loads(messages[-1]['content'])
        assert brief['user_instruction']=='立柱太矮了，尺寸不对'
        assert 'source_prompt' not in brief
        return {'content':json.dumps({'status':'needs_input','explanation':'缺少目标高度，可能与原比例锁定冲突'})}
    def vision(url,key,model,image,*args,**kwargs):
        events.append('original' if image.startswith(b'\xff\xd8') else 'source')
        return '当前成图立柱比例待核对' if image==png() else '原件显示展开管段与上部框架的连接关系，可按可见比例还原；不采用最高档。'
    prompt='Edit only the depicted upright assembly to restore its reference-supported proportions and connections. Adjust adjacent occlusion and shadows as needed. Preserve unrelated artwork.\nOutput: PNG.'
    def plan(*args,**kwargs):
        events.append('plan')
        brief=args[5]
        assert brief['intent']['status']=='needs_input'
        assert brief['revision_context']['source_prompt'].startswith('Preserve the existing height')
        if verdict!='unread':
            tools={tool.name:tool for tool in kwargs['extra_tools']}
            for material in brief['materials']:
                tools['view_material'].invoke({'name':'view_material','args':{'material_id':material['id'],'page':1},'id':material['id'],'type':'tool_call'})
        if verdict=='needs_input':
            return json.dumps({'status':'needs_input','explanation':'已核对说明书和实拍，展开档位存在冲突，请确认目标档位'}),{}
        return json.dumps({'status':'ready','user_issue':'还原立柱比例',
            'requested_changes':['按原件修复立柱比例及关联连接'],'preserve':['与纠错无关的正确内容'],
            'observed_issues':['成图管段比例与原件不符'],'correction_steps':['按展开原件还原管段和上部连接，适配局部遮挡'],
            'uncertainties':[],'prompt':prompt}),{}
    monkeypatch.setattr('app.agent_runtime._chat',chat)
    monkeypatch.setattr('app.agent_runtime._vision',vision)
    monkeypatch.setattr('app.skill_agent.plan_with_skills',plan)
    def execute(folder,profile,key,actual_prompt,reference):
        events.append('edit')
        assert verdict=='ready'
        assert actual_prompt==prompt
        assert reference==artifact(directory,source['id'],'result.png').read_bytes()
        return fake_executor(folder,profile,key,actual_prompt,reference)
    assert process_standard_one(store,execute,reviewer=lambda *args,**kwargs:{'status':'uncertain','summary':'待审核','checks':[]})
    value=client.get('/api/image-jobs/'+target['id']).json()
    record=value['execution_result']['revision_analysis']
    assert record['intent_needs_evidence'] is True
    assert record['intent']['explanation']=='缺少目标高度，可能与原比例锁定冲突'
    assert events[:3]==['understand','source','plan']
    assert artifact(directory,target['id'],'revision-intent-response.txt').is_file()
    if verdict=='ready':
        assert value['status']=='succeeded' and events[-1]=='edit'
        assert len(record['material_reads'])==2
    else:
        assert value['status']=='failed' and 'edit' not in events
        assert ('目标档位' if verdict=='needs_input' else '尚未实际核对') in value['message']


@pytest.mark.parametrize('crop',[None,[0.25,0.0,1.0,1.0]])
def test_planner_can_inspect_actual_edit_artwork_without_requesting_reupload(workflow,monkeypatch,crop):
    import hashlib
    import io
    from PIL import Image
    client,store,engine,directory,*_=workflow
    image=io.BytesIO();Image.new('RGB',(120,80),'red').save(image,'PNG');artwork=image.getvalue()
    first,_=submit(workflow,reference=png())
    def original_executor(folder,profile,key,prompt,reference):
        result=fake_executor(folder,profile,key,prompt,reference)
        (folder/'result.png').write_bytes(artwork)
        return result
    assert process_standard_one(store,original_executor)
    images,_=submit(workflow,prompt='立柱太矮了，尺寸不对',source_job_id=first[0]['id'])
    target=images[0]
    setup_planners(monkeypatch,[])
    observations=[]
    def vision(url,key,model,image,question,**kwargs):
        if image==artwork:
            assert kwargs['reference']==png()
            return '当前无法测得实际高度，不能据此证明尺寸错误。'
        # The new planner tool must see the generated artwork, not the identity photo.
        assert image.startswith(b'\xff\xd8')
        with Image.open(io.BytesIO(image)) as preview:
            assert preview.width<=1600 and preview.height<=1600
            red,green,blue=preview.convert('RGB').getpixel((0,0))
            assert red>200 and green<40 and blue<40
        observations.append(question)
        return '底图已核对：按用户要求增加立柱可见比例，同步修正上部连接与遮挡；不声称新增真实尺寸。'
    def plan(*args,**kwargs):
        brief=args[5];tools={tool.name:tool for tool in kwargs['extra_tools']}
        assert brief['edit_reference']['source_job_id']==first[0]['id']
        assert brief['edit_reference']['available'] is True
        assert brief['edit_reference']['role']=='actual_edit_input'
        assert brief['edit_reference']['sha256']==hashlib.sha256(artwork).hexdigest()
        tool=tools['view_edit_reference']
        assert '坐标无效' in tool.invoke({'crop':[-1,0,1,1]})
        assert not observations
        answer=json.loads(tool.invoke({'question':'按用户要求，核对立柱可见长度及连接如何调整','crop':crop}))
        assert answer['source_job_id']==first[0]['id'] and answer['crop']==crop
        assert '增加立柱可见比例' in answer['observation']
        return json.dumps({'status':'ready','user_issue':'按用户方向调整可见比例',
            'requested_changes':['增加立柱可见长度'],'preserve':['不相关内容'],
            'observed_issues':['用户希望立柱看起来更高，非实际尺寸测量结论'],
            'correction_steps':['调整可见长度、连接与遮挡'],'uncertainties':[],
            'prompt':'Edit only the upright assembly to look taller as requested, maintaining the actual tube connections and adapting adjacent occlusion. Preserve unrelated artwork.\nOutput: PNG.'}),{}
    monkeypatch.setattr('app.agent_runtime._vision',vision)
    monkeypatch.setattr('app.skill_agent.plan_with_skills',plan)
    def execute(folder,profile,key,prompt,reference):
        assert reference==artwork
        return fake_executor(folder,profile,key,prompt,reference)
    assert process_standard_one(store,execute,reviewer=lambda *args,**kwargs:{'status':'uncertain','summary':'待审核','checks':[]})
    value=client.get('/api/image-jobs/'+target['id']).json()
    assert value['status']=='succeeded',value['message']
    analysis=value['execution_result']['revision_analysis']
    assert len(analysis['edit_reference_reads'])==1
    assert analysis['edit_reference_reads'][0]['crop']==crop
    assert analysis['edit_reference_reads'][0]['sha256']==hashlib.sha256(artwork).hexdigest()
    assert not analysis['material_reads']  # Generated artwork must never count as original product evidence.
