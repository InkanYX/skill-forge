import json
import gzip
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.creation_projects import process_creation_one, run_planning
from app.database import CreationExecution
from app.image_provider import GenerationError
from app.product_research import (ResearchSettings, collect_research, normalized_reviews,
                                  snapshot_path, fingerprint, validate_ranked_points)
from app.sellersprite import ENDPOINT, SellerSpriteClient, ResearchError
from test_creation_projects import project_setup, upload
from test_standard_images import standard
from test_auth import accounts, member

ASIN = 'B000000001'
SECRET = 'test-shared-sellersprite-key'


class FakeClient:
    calls = None
    failure = None

    def __enter__(self): return self
    def __exit__(self, *args): pass

    def call(self, name, arguments):
        self.calls.append((name, arguments))
        if self.failure and self.failure(name, arguments):
            raise ResearchError('模拟查询超时，可能已扣额度。', uncertain=True)
        if name == 'asin.detail':
            return {'data': [{'asin': asin, 'title': '竞品庭院棚', 'parentAsin': asin} for asin in arguments['asins']]}
        if name == 'asin.content.list':
            return {'data': {'highlights': ['遮阳空间', '安装步骤']}}
        polarity = 'critical' if 1 in arguments['star'] else 'positive'
        return {'data': {'reviews': [{'reviewId': arguments['asin'] + polarity, 'title': '买家评价',
            'content': '安装说明需要更清楚' if polarity == 'critical' else '喜欢宽敞的遮阳空间',
            'rating': 2 if polarity == 'critical' else 5, 'date': '2026-11-20',
            'reviewerName': 'private-buyer', 'email': 'private@example.com'}],
            'collectionStatus': 'complete', 'coverageStart': '2026-10-01'}}


@pytest.fixture
def fake_client(monkeypatch):
    calls = []
    class Client(FakeClient): pass
    Client.calls = calls
    monkeypatch.setattr('app.product_research.SellerSpriteClient', Client)
    return Client, calls


def test_mcp_header_auth_streamable_http_and_allowlist():
    requests = []
    def handler(request):
        requests.append(request)
        assert str(request.url) == ENDPOINT and not request.url.query
        assert request.headers['secret-key'] == SECRET
        body = json.loads(request.content)
        if body['method'] == 'initialize':
            return httpx.Response(200, headers={'mcp-session-id': 'test-session'}, json={'jsonrpc': '2.0', 'id': 0,
                'result': {'protocolVersion': '2025-03-26'}})
        assert request.headers['Mcp-Session-Id'] == 'test-session'
        if body['method'] == 'notifications/initialized':
            return httpx.Response(202)
        assert body['params']['name'] == 'asin.review.list'
        event = {'jsonrpc': '2.0', 'id': 1, 'result': {'content': [{'type': 'text', 'text': '{"data":{"reviews":[]}}'}]}}
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, text='event: message\ndata: ' + json.dumps(event) + '\n\n')
    with SellerSpriteClient(SECRET, transport=httpx.MockTransport(handler)) as client:
        assert client.call('asin.review.list', {'marketplace': 'US', 'asin': ASIN, 'limit': 10}) == {'data': {'reviews': []}}
        with pytest.raises(ResearchError, match='未启用'): client.call('external.call', {})
    assert len(requests) == 3


@pytest.mark.parametrize('sse', [False, True])
def test_gzip_responses_are_decompressed_exactly_once(sse):
    def handler(request):
        body = json.loads(request.content)
        if body['method'] == 'notifications/initialized': return httpx.Response(202)
        result = {'protocolVersion': '2025-03-26'} if body['method'] == 'initialize' else {'structuredContent': {'data': {'reviews': []}}}
        data = json.dumps({'jsonrpc': '2.0', 'id': body['id'], 'result': result})
        data = 'data: ' + data + '\n\n' if sse else data
        return httpx.Response(200, headers={'content-encoding': 'gzip', 'content-type': 'text/event-stream' if sse else 'application/json'}, content=gzip.compress(data.encode()))
    with SellerSpriteClient(SECRET, transport=httpx.MockTransport(handler)) as client:
        assert client.call('asin.review.list', {}) == {'data': {'reviews': []}}


def test_sse_stops_at_matching_result_without_waiting_for_connection_close():
    class Events(httpx.SyncByteStream):
        def __iter__(self):
            yield b'data: {"jsonrpc":"2.0","method":"notifications/progress","params":{}}\n\n'
            yield b'data: {"jsonrpc":"2.0","id":99,"result":{}}\n\n'
            yield b'data: {"jsonrpc":"2.0","id":1,"result":{"structuredContent":{"data":[]}}}\n\n'
            raise AssertionError('Must stop reading after the matching result')
    def handler(request):
        body=json.loads(request.content)
        if body['method']=='initialize': return httpx.Response(200,json={'id':0,'result':{'protocolVersion':'2025-03-26'}})
        if body['method']=='notifications/initialized': return httpx.Response(202)
        return httpx.Response(200,headers={'content-type':'text/event-stream'},stream=Events())
    with SellerSpriteClient(SECRET,transport=httpx.MockTransport(handler)) as client:
        assert client.call('asin.review.list',{})=={'data':[]}


def test_handshake_failure_is_not_reported_as_a_paid_query_timeout(project_setup):
    _, store, _, _, project = project_setup
    def failing(request): raise httpx.ConnectError('secret-key=' + SECRET)
    factory=lambda: SellerSpriteClient(SECRET,transport=httpx.MockTransport(failing))
    report=collect_research(store,str(uuid4()),project['id'],ResearchSettings(enabled=True,own_asin=ASIN).model_dump(),client_factory=factory)
    assert report['sources']==[]
    assert report['connection_error']['phase']=='initialize'
    assert report['connection_error']['business_query_started'] is False
    assert SECRET not in json.dumps(report)


@pytest.mark.parametrize('business', [False, True])
def test_actual_read_timeout_identifies_phase_and_uncertain_business_result(business):
    calls=[]
    def handler(request):
        body=json.loads(request.content);calls.append(body['method'])
        if body['method']=='notifications/initialized': return httpx.Response(202)
        if body['method']=='initialize' and business:
            return httpx.Response(200,json={'id':0,'result':{'protocolVersion':'2025-03-26'}})
        raise httpx.ReadTimeout('secret-key='+SECRET)
    with pytest.raises(ResearchError) as caught:
        with SellerSpriteClient(SECRET,transport=httpx.MockTransport(handler)) as client:
            client.call('asin.review.list',{})
    error=caught.value
    assert error.uncertain==business
    assert error.diagnostic['phase']==('query' if business else 'initialize')
    assert error.diagnostic['error_type']=='ReadTimeout'
    assert SECRET not in error.message
    assert calls.count('tools/call')==(1 if business else 0)


@pytest.mark.parametrize('status', [401, 403, 500])
def test_mcp_errors_are_redacted_and_never_retried(status):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, text='secret-key=' + SECRET)
    with pytest.raises(ResearchError) as caught:
        with SellerSpriteClient(SECRET, transport=httpx.MockTransport(handler)): pass
    assert SECRET not in str(caught.value)
    assert len(calls) == 1
    assert caught.value.auth == (status in (401, 403))


def test_research_scope_validation_and_budget():
    value = ResearchSettings(enabled=True, competitor_asins=['b000000001', ASIN], reviews_per_asin=40)
    assert value.asins() == [ASIN]
    for body in ({'enabled': True}, {'enabled': True, 'own_asin': 'https://invalid'},
                 {'enabled': True, 'competitor_asins': [f'B00000000{i}' for i in range(3)], 'reviews_per_asin': 100},
                 {'secret-key': SECRET}):
        with pytest.raises(ValidationError): ResearchSettings.model_validate(body)


def test_research_cache_balanced_sampling_and_explicit_refresh(project_setup, fake_client):
    _, store, _, directory, project = project_setup
    _, calls = fake_client
    config = ResearchSettings(enabled=True, competitor_asins=[ASIN]).model_dump()
    first = collect_research(store, str(uuid4()), project['id'], config)
    assert first['status'] == 'ready' and first['review_count'] == 2
    assert len(calls) == 4 and first['planned_calls'] == 4
    reviews = [arguments for name, arguments in calls if name == 'asin.review.list']
    assert [item['star'] for item in reviews] == [[1, 2, 3], [4, 5]]
    assert sum(item['limit'] for item in reviews) == 40
    assert 'private-buyer' not in json.dumps(first) and 'private@example.com' not in json.dumps(first)
    assert any(source['data'].get('data', {}).get('collectionStatus') == 'complete'
               for source in first['sources'] if source['tool'] == 'asin.review.list')
    second = collect_research(store, str(uuid4()), project['id'], config)
    assert second['id'] == first['id'] and second['cache_hit'] and len(calls) == 4
    third = collect_research(store, str(uuid4()), project['id'], config, refresh=True)
    assert third['id'] != first['id'] and len(calls) == 8
    path = snapshot_path(directory, project['id'], fingerprint(ResearchSettings.model_validate(config)))
    assert (path.parent / 'versions' / (first['id'] + '.json')).is_file()


def test_unknown_paid_query_is_not_automatically_repeated(project_setup, fake_client):
    _, store, _, _, project = project_setup
    factory, calls = fake_client
    factory.failure = staticmethod(lambda name, args: name == 'asin.review.list' and 1 in args['star'])
    config = ResearchSettings(enabled=True, competitor_asins=[ASIN]).model_dump()
    first = collect_research(store, str(uuid4()), project['id'], config)
    assert first['status'] == 'partial' and len(calls) == 4
    second = collect_research(store, str(uuid4()), project['id'], config)
    assert len(calls) == 4 and second['id'] == first['id']
    assert any('可能已扣额度' in warning for warning in second['warnings'])


def test_auth_denial_stops_remaining_queries(project_setup):
    _, store, _, _, project = project_setup
    calls = []
    class Denied(FakeClient):
        def call(self, name, args):
            calls.append(name)
            raise ResearchError('模拟权限拒绝', auth=True)
    report = collect_research(store, str(uuid4()), project['id'],
        ResearchSettings(enabled=True, competitor_asins=[ASIN]).model_dump(), client_factory=Denied)
    assert calls == ['asin.detail'] and report['status'] == 'partial'


def test_duplicate_parent_reviews_are_not_double_counted():
    row = {'reviewId': 'same-parent-review', 'content': 'Good shade', 'rating': 5}
    steps = {str(i): {'name': 'asin.review.list', 'status': 'succeeded',
        'arguments': {'asin': asin, 'limit': 20}, 'data': {'reviews': [row]}}
        for i, asin in enumerate([ASIN, 'B000000002'])}
    assert len(normalized_reviews(steps, ResearchSettings(own_asin=ASIN))) == 1


def test_unsupported_claims_and_invented_citations_cannot_be_promoted():
    from app.product_research import RankedSellingPoint
    point = RankedSellingPoint(id='waterproof', title='防水', priority='P1', product_evidence='竞品说防水',
                               material_ids=['foreign'], review_ids=['invented']).model_dump()
    content = validate_ranked_points({'ranked_selling_points': [point]}, [{'id': 'actual'}], '', {'reviews': []})
    assert content['ranked_selling_points'][0]['priority'] == 'VERIFY'
    assert point['material_ids'] == [] and point['review_ids'] == []


def test_research_settings_analysis_snapshot_and_failed_planner_resume(project_setup, fake_client, monkeypatch):
    client, store, engine, _, _ = project_setup
    _, calls = fake_client
    project = client.post('/api/creation-projects', json={'title': '庭院棚', 'kind': 'product', 'goal': '产品有遮阳篷布'}).json()
    project = upload(client, project)
    url = '/api/creation-projects/' + project['id']
    config = ResearchSettings(enabled=True, competitor_asins=[ASIN]).model_dump()
    response = client.put(url + '/research-settings', json={'revision': project['revision'], 'settings': config})
    assert response.status_code == 200
    project = response.json()
    first = str(uuid4())
    assert client.post(url + '/stages/analysis', json={'revision': project['revision'], 'request_id': first}).status_code == 202
    def failing(*args): raise GenerationError('模拟文字模型失败')
    assert process_creation_one(store, failing)
    project = client.get(url).json()
    assert project['market_research']['review_count'] == 2 and len(calls) == 4
    def planner(store, execution, project_id, payload, stage):
        assert payload['market_research']['cache_hit']
        return {'facts': '实拍中有篷布', 'selling_points': '遮阳空间', 'questions': '', 'ranked_selling_points': [{
            'id': 'shade', 'title': '遮阳空间', 'priority': 'P1', 'product_evidence': '实拍中的篷布',
            'material_ids': [project['materials'][0]['id']], 'review_ids': [payload['market_research']['reviews'][0]['id']]}]}, {}
    assert client.post(url + '/stages/analysis', json={'revision': project['revision'], 'request_id': str(uuid4())}).status_code == 202
    assert process_creation_one(store, planner)
    project = client.get(url).json()
    content = project['documents']['analysis']['content']
    assert content['ranked_selling_points'][0]['priority'] == 'P1'
    assert len(content['ranked_selling_points'][0]['review_ids']) == 1
    assert content['research_snapshot']['id'] == project['market_research']['id']
    assert len(calls) == 4
    # Manual sorting preserves server-owned research, ignoring forged replacement reports.
    content['ranked_selling_points'][0]['priority'] = 'P2'
    content['research_snapshot'] = {'id': 'forged', 'reviews': []}
    edited = client.put(url + '/documents/analysis', json={'revision': project['revision'], 'content': content})
    assert edited.status_code == 200, edited.text
    assert edited.json()['documents']['analysis']['content']['research_snapshot']['id'] != 'forged'
    assert edited.json()['documents']['analysis']['content']['ranked_selling_points'][0]['priority'] == 'P2'


def test_shared_service_credentials_do_not_share_personal_products(accounts, monkeypatch):
    monkeypatch.setenv('SELLERSPRITE_MCP_SECRET_KEY', SECRET)
    alice, _ = member(accounts, 'research-alice')
    bob, _ = member(accounts, 'research-bob')
    for client in (alice, bob):
        response = client.get('/api/creation-projects/research-service')
        assert response.status_code == 200 and response.json()['configured']
        assert SECRET not in response.text
        assert client.get('/api/image-configs').json() is None
    project = alice.post('/api/creation-projects', json={'title': 'private product', 'kind': 'product'}).json()
    response = bob.put('/api/creation-projects/' + project['id'] + '/research-settings', json={
        'revision': project['revision'], 'settings': ResearchSettings().model_dump()})
    assert response.status_code == 404


def test_stale_research_settings_cannot_overwrite_newer_project(project_setup):
    client, _, _, _, _ = project_setup
    project = client.post('/api/creation-projects', json={'title': 'test product', 'kind': 'product'}).json()
    url = '/api/creation-projects/' + project['id'] + '/research-settings'
    body = {'revision': project['revision'], 'settings': ResearchSettings().model_dump()}
    assert client.put(url, json=body).status_code == 200
    assert client.put(url, json=body).status_code == 409


def test_analysis_prompt_requires_ranked_output_and_server_binds_snapshot(project_setup, monkeypatch):
    client, store, engine, _, project = project_setup
    request_id = str(uuid4())
    assert client.post('/api/creation-projects/' + project['id'] + '/stages/analysis', json={
        'revision': project['revision'], 'request_id': request_id}).status_code == 202
    with Session(engine) as session:
        payload = json.loads(session.get(CreationExecution, request_id).input)
    payload['market_research'] = {'id': 'real-snapshot', 'settings': {'marketplace': 'US'},
        'created_at': '2026-11-26', 'status': 'ready', 'warnings': [], 'sources': [],
        'reviews': [{'id': 'actual-review', 'text': '遮阳体验不错', 'asin': ASIN}]}
    def agent(engine, storage, directory, snapshot, instructions, brief, provider, **kwargs):
        assert 'ranked_selling_points' in brief['output_schema']['required']
        ranked_schema = brief['output_schema']['$defs']['RankedSellingPoint']
        assert 'review_mentions' in ranked_schema['required']
        assert 'review_metrics' not in ranked_schema['properties']
        assert 'research_snapshot' not in brief['output_schema']['properties']
        assert '不能新增或覆盖产品事实' in instructions
        assert brief['market_research']['reviews'][0]['id'] == 'actual-review'
        return json.dumps({'facts': '用户说明有产品资料', 'selling_points': '候选遮阳卖点', 'questions': '',
            'market_summary': '仅为有限评论样本', 'research_snapshot': {'id': 'forged'},
            'ranked_selling_points': [{'id': 'shade', 'title': '遮阳空间', 'priority': 'P1',
                'product_evidence': '用户产品说明', 'uses_product_description': True, 'review_ids': ['actual-review', 'invented'],
                'reviewed_review_ids': ['actual-review'], 'review_mentions': [
                    {'review_id': 'actual-review', 'sentiment': 'positive', 'quote': '遮阳体验不错'}],
                'review_metrics': {'forged': True}}]}), {}
    monkeypatch.setattr('app.skill_agent.plan_with_skills', agent)
    result, _ = run_planning(store, request_id, project['id'], payload, 'analysis')
    assert result['research_snapshot']['id'] == 'real-snapshot'
    assert result['ranked_selling_points'][0]['review_ids'] == ['actual-review']
    assert result['ranked_selling_points'][0]['review_metrics']['status'] == 'complete'
    assert result['ranked_selling_points'][0]['review_metrics']['groups']['all']['mentions'] == 1


def test_review_topic_counts_are_deduplicated_and_not_derived_from_stars():
    from app.product_research import RankedSellingPoint
    report = {'id': 'snapshot', 'reviews': [
        {'id': 'a', 'text': 'Easy assembly but poor shade', 'role': 'own', 'star': 5},
        {'id': 'b', 'text': 'Excellent shade', 'role': 'competitor', 'star': 1},
        {'id': 'c', 'text': 'Blue fabric', 'role': 'competitor', 'star': 4}]}
    point = RankedSellingPoint(id='shade', title='遮阳', priority='P1', product_evidence='篷布',
        material_ids=['m'], reviewed_review_ids=['a', 'b', 'c', 'forged'], review_mentions=[
            {'review_id': 'a', 'sentiment': 'negative', 'quote': 'poor shade'},
            {'review_id': 'a', 'sentiment': 'negative', 'quote': 'poor shade'},
            {'review_id': 'b', 'sentiment': 'positive', 'quote': 'Excellent shade'},
            {'review_id': 'forged', 'sentiment': 'positive', 'quote': 'invented'}],
        review_metrics={'groups': {'all': {'mentions': 999}}}).model_dump()
    validate_ranked_points({'ranked_selling_points': [point]}, [{'id': 'm'}], '', report)
    metrics = point['review_metrics']
    assert metrics['status'] == 'complete'
    assert metrics['groups']['all'] == dict(sample_count=3, reviewed_count=3, mentions=2,
        mention_rate=0.6667, positive=1, negative=1, neutral=0, mixed=0)
    assert metrics['groups']['own']['negative'] == 1
    assert metrics['groups']['competitor']['positive'] == 1
    assert metrics['own_negative_review_ids'] == ['a']
    assert point['review_ids'] == ['a', 'b']


def test_automatic_frequency_ordering_and_manual_order_are_distinct():
    from app.product_research import RankedSellingPoint
    report = {'id': 's', 'reviews': [{'id': 'a', 'text': 'shade assembly', 'role': 'competitor'},
                                  {'id': 'b', 'text': 'assembly', 'role': 'own'}]}
    def point(identifier, ids, evidence=True):
        return RankedSellingPoint(id=identifier, title=identifier, priority='P1',
            product_evidence='产品说明' if evidence else '', uses_product_description=True,
            reviewed_review_ids=['a', 'b'], review_mentions=[
                {'review_id': key, 'sentiment': 'neutral', 'quote': identifier} for key in ids]).model_dump()
    content = {'ranked_selling_points': [point('shade', ['a']), point('assembly', ['a', 'b']),
                                       point('assembly2', [], False)]}
    validate_ranked_points(content, [], '说明', report, auto_rank=True)
    assert [p['id'] for p in content['ranked_selling_points']] == ['assembly', 'shade', 'assembly2']
    content['ranked_selling_points'].reverse()
    validate_ranked_points(content, [], '说明', report)
    assert [p['id'] for p in content['ranked_selling_points']] == ['assembly2', 'shade', 'assembly']
    assert content['ranked_selling_points'][0]['priority'] == 'VERIFY'


def test_invalid_quotes_and_legacy_citations_are_not_fabricated_statistics():
    from app.product_research import RankedSellingPoint
    report = {'reviews': [{'id': 'a', 'text': 'real words', 'role': 'own'}]}
    point = RankedSellingPoint(id='x', title='x', review_ids=['a'], reviewed_review_ids=['a'],
        review_mentions=[{'review_id': 'a', 'sentiment': 'positive', 'quote': 'invented words'}]).model_dump()
    validate_ranked_points({'ranked_selling_points': [point]}, [], '', report)
    assert point['review_metrics']['status'] == 'unannotated'
    assert point['review_metrics']['groups']['all']['mentions'] == 0
    assert point['review_mentions'] == []
    legacy = RankedSellingPoint(id='old', title='old', review_ids=['a']).model_dump()
    validate_ranked_points({'ranked_selling_points': [legacy]}, [], '', report)
    assert legacy['review_metrics']['status'] == 'unannotated'
    assert legacy['review_ids'] == ['a']


def test_partial_coverage_does_not_reorder_and_mixed_reviews_count_once():
    from app.product_research import RankedSellingPoint
    report = {'reviews': [{'id': 'a', 'text': 'shade and setup', 'role': 'own'},
                          {'id': 'b', 'text': 'shade', 'role': 'competitor'}]}
    points = [RankedSellingPoint(id='setup', title='setup', priority='P2',
        product_evidence='产品说明', uses_product_description=True, reviewed_review_ids=['a']).model_dump(),
        RankedSellingPoint(id='shade', title='shade', priority='P1', product_evidence='产品说明',
            uses_product_description=True, reviewed_review_ids=['a', 'b'], review_mentions=[
                {'review_id': 'a', 'sentiment': 'mixed', 'quote': 'shade'},
                {'review_id': 'b', 'sentiment': 'positive', 'quote': 'shade'}]).model_dump()]
    content = validate_ranked_points({'ranked_selling_points': points}, [], '资料', report, auto_rank=True)
    assert [p['id'] for p in content['ranked_selling_points']] == ['setup', 'shade']
    assert points[0]['review_metrics']['status'] == 'partial'
    counts = points[1]['review_metrics']['groups']['all']
    assert counts['mentions'] == 2 and counts['mixed'] == 1 and counts['positive'] == 1
    assert sum(counts[label] for label in ('positive', 'negative', 'neutral', 'mixed')) == 2
