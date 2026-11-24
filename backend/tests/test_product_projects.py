"""Stage boundaries and recovery are tested without sending any provider requests."""
import io
import json
import hashlib
from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.agent_runtime import AgentError
from app.database import ProductImageProject, ImageConfiguration, ImageJob
from app.project_materials import prepare_asset, page_preview, asset_root
from app.project_runtime import process_project_one
from app.standard_image_worker import process_standard_one
from test_agent_runtime import setup, save_config, install_skill, png


def project(setup, count=2):
    client, store, engine, directory = setup
    config = save_config(client)
    skill = install_skill(client)
    response = client.post('/api/product-projects', json={'title': '庭院商品套图', 'sku': 'SKU-A',
        'brief': '英文文案，保持原产品结构', 'skill_id': skill['id'], 'config_id': config['id'],
        'image_count': count})
    assert response.status_code == 201, response.text
    p = response.json()
    response = client.post(f"/api/product-projects/{p['id']}/assets", data={
        'revision':p['revision'], 'asset_id':str(uuid4()), 'role':'product_identity'},
        files={'file':('product.png',png(),'image/png')})
    assert response.status_code == 200, response.text
    return response.json()


def current(setup, p):
    response = setup[0].get('/api/product-projects/'+p['id'])
    assert response.status_code == 200, response.text
    return response.json()


def cmd(setup, p, action, expected=200, **values):
    response = setup[0].post(f"/api/product-projects/{p['id']}/commands", json={'revision':p['revision'], 'action':action, **values})
    assert response.status_code == expected, response.text
    return response.json()


def points(p):
    return {'summary':'保留可见设计卖点，性能另需证明。','identity':'灰色框架，四根立柱，保持连接与自然比例。',
        'claims':[{'id':'C1','text':'灰色四柱框架','source_ids':[p['assets'][0]['id']], 'status':'supported','boundary':'仅限可见外观'},
                  {'id':'C2','text':'抗风待检测','source_ids':[p['assets'][0]['id']], 'status':'needs_evidence','boundary':'不能用于成品'}],
        'points':[{'id':'P1','title':'简洁庭院外观','feature':'灰色四柱框架','benefit':'便于选择庭院配色',
                   'claim_ids':['C1'],'status':'supported','visual':'展示四柱全貌','conditions':'','priority':'primary'},
                  {'id':'P2','title':'抗风候选','feature':'框架','benefit':'防护假设','claim_ids':['C2'],
                   'status':'needs_evidence','visual':'待检测报告','conditions':'缺检测','priority':'excluded'}],
        'unknowns':['抗风性能未提供证明']}


def plan(p):
    return {'summary':'先完整识别，再展示场景。','visual_system':'米白、深灰、鼠尾草绿；标题左上，5%边距；柔光，接地阴影真实。',
        'shots':[{'id':f'S{i+1}', 'name':f'图片{i+1}', 'kind':'main' if i==0 else 'secondary',
            'question':'产品外观是否适合庭院？','point_ids':['P1'],'claim_ids':['C1'],
            'scene':'纯白背景' if i==0 else '傍晚庭院，石板地面，远处植物',
            'camera':'三分之四全景，完整屋顶与脚座','composition':'产品居中，保留5%边距，文案不遮挡关键结构',
            'lighting':'柔和左上光，真实阴影','props':'不新增配件，不暗示家具包含',
            'copy':[] if i==0 else [{'text':'Made for Your Garden','claim_ids':[]}],
            'typography':'主图无字' if i==0 else '深灰衬线标题，浅底，左上，不超过两行',
            'reference_asset_id':p['assets'][0]['id'],'aspect_ratio':'1:1','acceptance':['四柱数量一致','无编造参数'],
            'information_gain':'整体身份' if i==0 else '庭院配色与场景用途'} for i in range(p['image_count'])]}


def main_prompt():
    return 'Task and selling objective: complete product on a clean white background.\nReference roles: Reference 1 is the product identity reference.\nProduct identity lock: preserve all four gray posts and connections.\nScene and camera: full three-quarter view.\nOutput: one PNG, no generated text, no props.'


def finished_prompt():
    return '\n'.join([
        'Task and selling objective: Create one finished marketplace image.',
        'Reference roles: Reference 1 is the product identity reference.',
        'Product identity lock: preserve all four gray posts and connections.',
        'Scene and camera: evening garden with stone ground.',
        'Composition and hierarchy: full product right, title upper left, safe margins 5%.',
        'Art direction and physical realism: muted green and ivory, coherent contact shadows.',
        'Exact copy: Headline: "Made for Your Garden"',
        'Typography and graphic layout: charcoal serif headline, two lines maximum.',
        'Strict exclusions: do not invent claims or accessories.',
        'Output: one complete finished image, PNG, with all specified copy rendered.'])


def worker(setup, **kwargs):
    _, store, engine, directory = setup
    return process_project_one(engine, directory, store, **kwargs)


def draft_points(setup, p):
    cmd(setup,p,'analyze',authorized=True)
    vision_calls=[]
    def vision(url,key,model,image,question):
        assert image.startswith(b'\xff\xd8')
        vision_calls.append(question)
        return '可见灰色四柱，性能未知。'
    worker(setup,vision=vision)
    assert len(vision_calls)==1
    p=current(setup,p)
    assert p['status']=='queued'
    def chat(url,key,model,messages):
        assert '没有生图工具' in messages[0]['content']
        return {'content':json.dumps(points(p),ensure_ascii=False)}
    worker(setup,chat=chat)
    p=current(setup,p)
    assert p['status']=='waiting_points'
    return p


def draft_plan(setup, p):
    p=cmd(setup,p,'approve_points',point_ids=['P1'])
    p=cmd(setup,p,'plan',message='温暖户外风，保持四根立柱')
    worker(setup,chat=lambda *a:{'content':json.dumps(plan(p),ensure_ascii=False)})
    p=current(setup,p)
    assert p['status']=='waiting_plan',p['error']
    return p


def verify_config(setup):
    _,store,engine,_=setup
    with Session(engine) as session,session.begin():
        config=session.scalars(select(ImageConfiguration)).first()
        # Verification status is deliberately supplied by a mock, never a paid probe.
        config.generation_job_id='test-generate'
        config.edit_job_id='test-edit'
    original=store.result
    store.result=lambda session,identifier: {'status':'succeeded','job_id':identifier,'task_id':identifier,'updated_at':None} if identifier in ('test-generate','test-edit') else original(session,identifier)


def finish_job(directory,profile,key,prompt,reference):
    assert reference is not None
    assert profile['quality']=='high' and profile['size']=='auto'
    assert profile['model']=='gpt-image-2.5-sunburst'
    directory.mkdir(parents=True,exist_ok=True)
    (directory/'result.png').write_bytes(png())
    Image.new('RGB',(16,16),'gray').save(directory/'preview.jpg','JPEG')
    return {'native_pixels':[16,16], 'output_sha256':hashlib.sha256(png()).hexdigest()}


def generate_all(setup,p):
    verify_config(setup)
    p=cmd(setup,p,'generate')
    def chat(url,key,model,messages):
        data=json.loads(messages[-1]['content'].split('\n',1)[1])
        return {'content':json.dumps({'prompt':main_prompt() if data['shot']['kind']=='main' else finished_prompt()})}
    for _ in range(14):
        worker(setup,chat=chat,vision=lambda *a:'结构数量与文案建议人工复核，无新增性能主张。')
        process_standard_one(setup[1],executor=finish_job)
        p=current(setup,p)
        if p['status'] in ('review','blocked'):
            break
    assert p['status']=='review',p['error']
    return p


def test_full_staged_flow_persists_sources_gates_prompts_jobs_and_qc(setup):
    p=project(setup)
    cmd(setup,p,'generate',expected=409)
    cmd(setup,p,'plan',expected=409)
    cmd(setup,p,'analyze',expected=422)
    p=draft_points(setup,p)
    cmd(setup,p,'approve_points',point_ids=['P2'],expected=422)
    assert setup[0].get('/api/image-jobs').json()==[]
    p=draft_plan(setup,p)
    cmd(setup,p,'generate',expected=409) # provider generation/edit capability gates
    p=generate_all(setup,p)
    assert len(p['outputs'])==2
    for output in p['outputs']:
        assert output['job']['mode']=='edit'
        assert output['native_pixels']==[16,16]
        assert output['human_review']=='pending'
        assert output['qc']['status']=='needs_human_review'
        assert output['reference']['role']=='product_identity'
        assert setup[0].get(f"/api/product-projects/{p['id']}/outputs/{output['id']}/prompt").status_code==200
    with Session(setup[2]) as session:
        assert session.scalar(select(func.count()).select_from(ImageJob))==2
    cmd(setup,p,'generate',expected=409)
    review=setup[0].post(f"/api/product-projects/{p['id']}/outputs/{p['outputs'][0]['id']}/review",json={'revision':p['revision'],'status':'passed','notes':'四柱及原生尺寸已核对'})
    assert review.status_code==200,review.text
    assert review.json()['outputs'][0]['human_review']=='passed'
    p=review.json()
    review=setup[0].post(f"/api/product-projects/{p['id']}/outputs/{p['outputs'][1]['id']}/review",json={'revision':p['revision'],'status':'passed','notes':'原图逐字核对无 P0/P1'})
    assert review.status_code==200 and review.json()['status']=='completed'


def test_stale_edit_and_double_confirmation_are_rejected(setup):
    p=draft_points(setup,project(setup))
    old=p
    p=cmd(setup,p,'approve_points',point_ids=['P1'])
    cmd(setup,old,'approve_points',point_ids=['P1'],expected=409)
    p=cmd(setup,p,'plan')
    cmd(setup,p,'plan',expected=409)


def test_discussion_invalidates_downstream_approvals_but_preserves_outputs(setup):
    p=draft_plan(setup,draft_points(setup,project(setup)))
    old_plan=deepcopy(p['plan'])
    p=cmd(setup,p,'discuss_points',message='保留外观，收窄收益，不要抗风')
    value=points(p);value['points'][0]['benefit']='帮助判断配色'
    worker(setup,chat=lambda *a:{'content':json.dumps(value,ensure_ascii=False)})
    p=current(setup,p)
    assert p['points_approval'] is None and p['plan_approval'] is None
    assert p['plan']==old_plan
    p=cmd(setup,p,'approve_points',point_ids=['P1'])
    cmd(setup,p,'generate',expected=409)


def test_one_changed_shot_reuses_other_images_without_paid_resubmission(setup):
    p=generate_all(setup,draft_plan(setup,draft_points(setup,project(setup))))
    old_jobs={o['shot_id']:o['job_id'] for o in p['outputs']}
    changed=deepcopy(p['plan']);changed['shots'][1]['scene']='黎明庭院，石板地面，远处植物'
    response=setup[0].put(f"/api/product-projects/{p['id']}/artifacts",json={'revision':p['revision'],'plan':changed})
    assert response.status_code==200,response.text
    p=generate_all(setup,response.json())
    version=[o for o in p['outputs'] if o['plan_version']==p['plan_version']]
    assert version[0]['inherited_from'] and version[0]['job_id']==old_jobs['S1']
    assert version[1]['job_id']!=old_jobs['S2']
    with Session(setup[2]) as session:
        assert session.scalar(select(func.count()).select_from(ImageJob))==3


def test_unknown_image_blocks_remaining_shots_and_resume_never_reorders(setup):
    p=draft_plan(setup,draft_points(setup,project(setup)))
    verify_config(setup);p=cmd(setup,p,'generate')
    worker(setup,chat=lambda *a:{'content':json.dumps({'prompt':main_prompt()})})
    p=current(setup,p)
    with Session(setup[2]) as session,session.begin():
        job=session.get(ImageJob,p['outputs'][0]['job_id'])
        job.status,job.message='unknown','超时可能计费，请核对服务商状态'
    worker(setup)
    p=current(setup,p)
    assert p['status']=='blocked' and '未重试' in p['error']
    p=cmd(setup,p,'resume')
    worker(setup)
    p=current(setup,p)
    assert p['status']=='blocked'
    with Session(setup[2]) as session:
        assert session.scalar(select(func.count()).select_from(ImageJob))==1


def test_403_stops_without_retry_or_image_submission(setup):
    p=project(setup);cmd(setup,p,'analyze',authorized=True)
    calls=[]
    def denied(*a):
        calls.append(1);raise AgentError('鉴权或权限校验失败，未重试。')
    worker(setup,vision=denied)
    assert not worker(setup,vision=denied)
    p=current(setup,p)
    assert p['status']=='blocked' and len(calls)==1
    assert setup[0].get('/api/image-jobs').json()==[]


def test_cancellation_wins_over_inflight_ai_result(setup):
    p=project(setup);cmd(setup,p,'analyze',authorized=True)
    def cancelled(*args):
        cmd(setup,current(setup,p),'cancel')
        return '灰色四柱'
    worker(setup,vision=cancelled)
    p=current(setup,p)
    assert p['status']=='cancelled' and not p['assets'][0]['analysis']


def test_project_is_private_even_when_identifier_is_known(setup):
    p=project(setup)
    with TestClient(setup[0].app) as other:
        save_config(other)
        assert other.get('/api/product-projects').json()==[]
        assert other.get('/api/product-projects/'+p['id']).status_code==404
        assert other.get(f"/api/product-projects/{p['id']}/assets/{p['assets'][0]['id']}/original").status_code==404
        assert other.post(f"/api/product-projects/{p['id']}/commands",json={'revision':p['revision'],'action':'analyze','authorized':True}).status_code==404


def pdf(text=True):
    writer=PdfWriter();page=writer.add_blank_page(width=300,height=300)
    if text:
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
        stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 20 240 Td (Width 3 m) Tj ET')
        page[NameObject('/Contents')]=writer._add_object(stream)
    out=io.BytesIO();writer.write(out);return out.getvalue()


def test_pdf_text_page_sources_scanned_pages_and_originals_are_preserved(setup):
    p=project(setup,count=1)
    for text in (True,False):
        content=pdf(text)
        response=setup[0].post(f"/api/product-projects/{p['id']}/assets",data={'revision':p['revision'],'asset_id':str(uuid4()),'role':'manual'},files={'file':('manual.pdf',content,'application/pdf')})
        assert response.status_code==200,response.text
        p=response.json();asset=p['assets'][-1]
        assert ('Width 3 m' in asset['pages'][0]['text'])==text
        assert setup[0].get(f"/api/product-projects/{p['id']}/assets/{asset['id']}/original").content==content
        preview=page_preview(setup[3],p['id'],asset['id'],1)
        assert preview.startswith(b'\xff\xd8')
    cmd(setup,p,'analyze',authorized=True)
    seen=[]
    def vision(url,key,model,image,question):
        seen.append(question);return '本页尺寸或图形已识读，不确定项保留。'
    for _ in range(3):worker(setup,vision=vision)
    p=current(setup,p)
    assert all(page['method']=='text+vision' for a in p['assets'] for page in a.get('pages',[]))
    assert len(seen)==3 and any(':p1' in question for question in seen)


def test_invalid_pdf_wrong_role_and_excess_pages_are_rejected():
    for content,role in [(b'%PDF-broken','manual'),(pdf(),'product_identity'),(png(),'manual')]:
        with pytest.raises(Exception):prepare_asset(content,'manual.pdf',role,str(uuid4()))
    writer=PdfWriter()
    for _ in range(41):writer.add_blank_page(100,100)
    output=io.BytesIO();writer.write(output)
    with pytest.raises(Exception):prepare_asset(output.getvalue(),'huge.pdf','manual',str(uuid4()))


def test_fabricated_source_and_unapproved_points_never_replace_draft(setup):
    p=draft_points(setup,project(setup))
    modified=points(p);modified['claims'][0]['source_ids']=['invented.pdf:p999']
    response=setup[0].put(f"/api/product-projects/{p['id']}/artifacts",json={'revision':p['revision'],'points':modified})
    assert response.status_code==422
    assert current(setup,p)['points_version']==1
    p=draft_plan(setup,p)
    modified=deepcopy(p['plan']);modified['shots'][0]['point_ids']=['P2']
    response=setup[0].put(f"/api/product-projects/{p['id']}/artifacts",json={'revision':p['revision'],'plan':modified})
    assert response.status_code==422


def test_added_source_invalidates_authorization_and_both_gates(setup):
    p=draft_plan(setup,draft_points(setup,project(setup)))
    response=setup[0].post(f"/api/product-projects/{p['id']}/assets",data={'revision':p['revision'],'asset_id':str(uuid4()),'role':'specification'},files={'file':('spec.pdf',pdf(),'application/pdf')})
    assert response.status_code==200,response.text
    p=response.json()
    assert p['authorization'] is None and p['points_approval'] is None and p['plan_approval'] is None
    cmd(setup,p,'generate',expected=409)


def test_waiting_confirmations_survive_worker_restart_without_calls(setup):
    p=draft_points(setup,project(setup))
    def unexpected(*args):
        raise AssertionError('等待人工确认时不应调用模型')
    assert not worker(setup,chat=unexpected,vision=unexpected)
    p=current(setup,p)
    assert p['status']=='waiting_points' and p['points_version']==1
    p=cmd(setup,p,'approve_points',point_ids=['P1'])
    assert not worker(setup,chat=unexpected,vision=unexpected)
    assert current(setup,p)['points_approval']==1


def test_lost_enqueue_acknowledgment_reconciles_deterministic_job_id(setup,monkeypatch):
    import app.project_runtime as runtime
    p=draft_plan(setup,draft_points(setup,project(setup,count=1)))
    verify_config(setup);p=cmd(setup,p,'generate')
    original=runtime.create_jobs
    def lost(*args,**kwargs):
        original(*args,**kwargs)
        raise RuntimeError('simulate local interruption after job commit')
    monkeypatch.setattr(runtime,'create_jobs',lost)
    worker(setup,chat=lambda *a:{'content':json.dumps({'prompt':main_prompt()})})
    p=current(setup,p)
    assert p['status']=='blocked' and not p['outputs'][0]['job_id']
    with Session(setup[2]) as session:
        first=session.scalars(select(ImageJob)).one().id
    monkeypatch.setattr(runtime,'create_jobs',original)
    p=cmd(setup,p,'resume')
    worker(setup)
    p=current(setup,p)
    assert p['outputs'][0]['job_id']==first
    with Session(setup[2]) as session:
        assert session.scalar(select(func.count()).select_from(ImageJob))==1


def test_expired_running_stage_is_blocked_and_not_replayed(setup):
    p=project(setup);p=cmd(setup,p,'analyze',authorized=True)
    with Session(setup[2]) as session,session.begin():
        row=session.get(ProductImageProject,p['id'])
        row.status,row.lease_until='running',1
    calls=[]
    assert not worker(setup,vision=lambda *a:calls.append(1))
    p=current(setup,p)
    assert p['status']=='blocked' and not calls
    assert p['interrupted_action']=='analyze'


def test_qc_auth_failure_stops_remaining_images_without_retries(setup):
    p=draft_plan(setup,draft_points(setup,project(setup)))
    verify_config(setup);p=cmd(setup,p,'generate')
    worker(setup,chat=lambda *a:{'content':json.dumps({'prompt':main_prompt()})})
    process_standard_one(setup[1],executor=finish_job)
    calls=[]
    def denied(*a):
        calls.append(1);raise AgentError('403 权限拒绝，未重试')
    worker(setup,vision=denied)
    p=current(setup,p)
    assert p['status']=='blocked' and p['outputs'][0]['qc']['status']=='unavailable'
    assert not worker(setup,vision=denied)
    assert len(calls)==1
    with Session(setup[2]) as session:
        assert session.scalar(select(func.count()).select_from(ImageJob))==1


def test_text_provider_change_requires_new_material_authorization(setup):
    p=draft_points(setup,project(setup))
    old=setup[1].resolve_text
    setup[1].resolve_text=lambda owner:('https://different.example.com/v1','secret','text-model')
    p=cmd(setup,p,'approve_points',point_ids=['P1'])
    cmd(setup,p,'plan',expected=409)
    setup[1].resolve_text=old


def test_answer_only_discussion_preserves_unchanged_approval(setup):
    p=draft_plan(setup,draft_points(setup,project(setup)))
    value=deepcopy(p['points']);value['summary']='这个外观卖点基于可见配色和结构。'
    p=cmd(setup,p,'discuss_points',message='解释一下外观卖点的依据，不修改卖点')
    worker(setup,chat=lambda *a:{'content':json.dumps(value,ensure_ascii=False)})
    p=current(setup,p)
    assert p['points_version']==1 and p['points_approval']==1
    assert p['status']=='waiting_plan'


def test_missing_native_result_is_reported_instead_of_regenerated(setup):
    p=generate_all(setup,draft_plan(setup,draft_points(setup,project(setup))))
    first_job=p['outputs'][0]['job_id']
    (setup[3]/'image-jobs'/first_job/'result.png').unlink()
    changed=deepcopy(p['plan']);changed['shots'][1]['scene']='新场景，仅第二张变化'
    response=setup[0].put(f"/api/product-projects/{p['id']}/artifacts",json={'revision':p['revision'],'plan':changed})
    assert response.status_code==200,response.text
    p=cmd(setup,response.json(),'generate')
    worker(setup)
    p=current(setup,p)
    assert p['status']=='blocked' and '原生文件缺失或校验不符' in p['error']
    with Session(setup[2]) as session:
        assert session.scalar(select(func.count()).select_from(ImageJob))==2
