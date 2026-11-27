import copy
import json
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.agent_runtime import AgentError
from app.analysis_pipeline import ReviewBatch, assess_batch, request_json
from app.creation_projects import process_creation_one
from app.database import CreationProject, CreationExecution
from app.product_research import RankedSellingPoint, ResearchSettings
from test_creation_projects import project_setup
from test_standard_images import standard


@pytest.fixture
def pipeline(project_setup, monkeypatch):
    client, store, engine, _, _ = project_setup
    project = client.post('/api/creation-projects', json={'title': '庭院棚', 'kind': 'product',
        'goal': '四根立柱和遮阳篷布', 'planning_model': 'planner'}).json()
    url = '/api/creation-projects/' + project['id']
    settings = ResearchSettings(enabled=True, competitor_asins=['B000000001']).model_dump()
    project = client.put(url + '/research-settings', json={'revision': project['revision'], 'settings': settings}).json()
    report = {'id': 'snapshot', 'settings': settings, 'created_at': '2026-11-26T00:00:00Z',
        'updated_at': '2026-11-26T00:00:00Z', 'status': 'ready', 'warnings': [], 'sources': [],
        'reviews': [{'id': str(i), 'title': '', 'text': 'Good shade', 'role': 'competitor', 'asin': 'B000000001'} for i in range(7)],
        'review_count': 7, 'cache_hit': False}
    calls = {'base': 0, 'research': 0, 'batches': [], 'ranking': 0}
    controls = {'fail_batch': None, 'fail_ranking': False, 'bad_quote': False, 'fail_base': False}
    def base_planner(store, execution_id, project_id, payload, stage):
        calls['base'] += 1
        assert payload['analysis_phase'] == 'materials' and 'market_research' not in payload
        if controls['fail_base']: raise AgentError('模拟资料分析超时')
        return {'facts': '用户说明四根立柱和遮阳篷布', 'selling_points': '宽敞遮阳空间', 'questions': '',
            'ranked_selling_points': [RankedSellingPoint(id='shade', title='遮阳空间', priority='P1',
                product_evidence='用户说明有篷布', uses_product_description=True).model_dump()]}, {'materials': [], 'used_skills': []}
    def research(*args, **kwargs):
        calls['research'] += 1
        return copy.deepcopy(report)
    def model(store, payload, instructions, body, schema):
        if schema is ReviewBatch:
            ids = [review['id'] for review in body['reviews']]
            calls['batches'].append(ids)
            if controls['fail_batch'] == ids[0]: raise AgentError('模拟评论请求超时')
            return {'content': json.dumps({'assessments': [{'review_id': identifier, 'matches': [
                {'point_id': 'shade', 'review_id': identifier, 'sentiment': 'positive',
                 'quote': 'invented' if controls['bad_quote'] else 'Good shade'}]} for identifier in ids]})}
        calls['ranking'] += 1
        if controls['fail_ranking']: raise AgentError('模拟汇总请求超时')
        return {'content': json.dumps({'market_summary': '样本关注遮阳空间', 'points': [
            {'id': 'shade', 'priority': 'P1', 'reason': '七条样本提及，且有产品说明依据',
             'buyer_need': '遮阳', 'display_suggestion': '庭院场景', 'expression_limits': ''}]})}
    monkeypatch.setattr('app.creation_projects.run_planning', base_planner)
    monkeypatch.setattr('app.analysis_pipeline.collect_research', research)
    monkeypatch.setattr('app.analysis_pipeline.request_json', model)
    def run(resume=False, **extra):
        current = client.get(url).json()
        response = client.post(url + '/stages/analysis', json={'revision': current['revision'],
            'request_id': str(uuid4()), 'resume_analysis': resume, **extra})
        if response.status_code == 202:
            assert process_creation_one(store)
        return response, client.get(url).json()
    return client, store, engine, url, calls, controls, run


def test_batch_timeout_preserves_visible_selling_points_and_resumes_exact_remaining_work(pipeline):
    client, _, _, url, calls, controls, run = pipeline
    controls['fail_batch'] = '6'
    _, failed = run(instruction='重点核对篷布')
    assert failed['executions'][-1]['status'] == 'failed'
    assert '继续未完成分析' in failed['executions'][-1]['error']
    base = failed['documents']['analysis']
    assert base['content']['facts'] and base['content']['ranked_selling_points'][0]['title'] == '遮阳空间'
    assert base['confirmed_at'] is None
    assert failed['analysis_pipeline']['completed_batches'] == 1
    assert failed['analysis_pipeline']['can_resume'] is True
    premature = client.post(url + '/documents/analysis/confirm', json={'revision': failed['revision']})
    assert premature.status_code == 409
    controls['fail_batch'] = None
    response, finished = run(resume=True)
    assert response.status_code == 202, response.text
    assert finished['executions'][-1]['status'] == 'succeeded', finished['executions'][-1]['error']
    assert calls['base'] == 1 and calls['research'] == 1
    assert calls['batches'] == [[str(i) for i in range(6)], ['6'], ['6']]
    assert finished['analysis_pipeline']['status'] == 'completed'
    assert finished['analysis_pipeline']['can_resume'] is False
    assert len(finished['history']) == 2
    point = finished['documents']['analysis']['content']['ranked_selling_points'][0]
    assert point['review_metrics']['groups']['all']['mentions'] == 7
    assert point['review_metrics']['status'] == 'complete'
    assert finished['documents']['analysis']['content']['research_snapshot']['id'] == 'snapshot'
    assert client.get(url).json()['documents']['analysis']['id'] != base['id']


def test_ranking_retry_does_not_repeat_completed_review_batches_or_refresh(pipeline):
    _, _, _, _, calls, controls, run = pipeline
    controls['fail_ranking'] = True
    _, failed = run(refresh_research=True)
    assert failed['analysis_pipeline']['completed_batches'] == 2
    assert failed['analysis_pipeline']['phase'] == 'ranking'
    controls['fail_ranking'] = False
    _, completed = run(resume=True)
    assert completed['executions'][-1]['status'] == 'succeeded'
    assert calls == {'base': 1, 'research': 1, 'batches': [[str(i) for i in range(6)], ['6']], 'ranking': 2}


def test_changed_material_facts_and_manual_edits_cannot_be_overwritten_by_resume(pipeline):
    client, _, engine, url, _, controls, run = pipeline
    controls['fail_ranking'] = True
    _, failed = run()
    with Session(engine) as session, session.begin():
        project = session.get(CreationProject, failed['id'])
        data = json.loads(project.content)
        data['goal'] = '已经更换产品规格'
        project.content = json.dumps(data)
    response, _ = run(resume=True)
    assert response.status_code == 409
    assert '已改变' in response.json()['detail']
    # Even a same-text manual document save is a different author-owned version.
    current = client.get(url).json()
    saved = client.put(url + '/documents/analysis', json={'revision': current['revision'],
        'content': current['documents']['analysis']['content']})
    assert saved.status_code == 200
    response, _ = run(resume=True)
    assert response.status_code == 409 and '卖点已被修改' in response.json()['detail']


def test_bad_review_quote_stops_once_without_committing_batch(pipeline):
    _, _, _, _, calls, controls, run = pipeline
    controls['bad_quote'] = True
    _, failed = run()
    assert failed['executions'][-1]['status'] == 'failed'
    assert failed['analysis_pipeline']['completed_batches'] == 0
    assert len(calls['batches']) == 1 and calls['ranking'] == 0


def test_material_phase_failure_does_not_start_paid_market_research(pipeline):
    _, _, _, _, calls, controls, run = pipeline
    controls['fail_base'] = True
    _, failed = run()
    assert failed['executions'][-1]['status'] == 'failed'
    assert failed['documents']['analysis'] is None
    assert calls['research'] == 0 and calls['batches'] == []
    controls['fail_base'] = False
    response, completed = run(resume=True)
    assert response.status_code == 202, response.text
    assert completed['executions'][-1]['status'] == 'succeeded'


def test_resume_cannot_force_new_research_or_change_original_instruction(pipeline):
    _, _, _, _, _, controls, run = pipeline
    controls['fail_ranking'] = True
    run(instruction='原要求')
    response, _ = run(resume=True, refresh_research=True)
    assert response.status_code == 422
    response, _ = run(resume=True, instruction='新要求')
    assert response.status_code == 409


def test_small_review_calls_keep_original_model_and_use_no_image_or_tool_context(project_setup, monkeypatch):
    _, store, _, _, _ = project_setup
    profile = {'id': 'config', 'revision': 'v', 'base_url': 'https://provider.example/v1',
        'model': 'configured-model', 'parameters': {'temperature': .2}}
    monkeypatch.setattr(store, 'key', lambda *args: 'test-key')
    calls = []
    def chat(base_url, key, model, messages, **kwargs):
        calls.append((model, messages, kwargs))
        return {'content': '{"assessments": []}'}
    monkeypatch.setattr('app.agent_runtime._chat', chat)
    result = request_json(store, {'profile': profile}, '检查评论', {'reviews': []}, ReviewBatch)
    assert result['content']
    assert calls[0][0] == 'configured-model'
    assert calls[0][2] == {'timeout': 240, 'parameters': {'temperature': .2}}
    assert 'data:image' not in json.dumps(calls[0][1])


def test_batch_cannot_silently_omit_unmatched_reviews(pipeline, monkeypatch):
    _, store, _, _, _, _, _ = pipeline
    monkeypatch.setattr('app.analysis_pipeline.request_json', lambda *args: {'content': '{"assessments": []}'})
    with pytest.raises(ValueError, match='未完成全部评论'):
        assess_batch(store, {}, {'ranked_selling_points': []}, [{'id': 'a', 'text': 'no match', 'title': ''}])
