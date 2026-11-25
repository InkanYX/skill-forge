"""Apply a pinned skill before the paid image call; review the actual output."""
import hashlib
import json
import shutil
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError

from app.agent_review import REVIEW_INSTRUCTIONS, parse_review
from app.agent_tools import lint_prompt
from app.creation_skills import skill_context
from app.image_provider import GenerationError


class PreparedPrompt(BaseModel):
    status: Literal['ready', 'needs_input']
    prompt: str = Field(default='', max_length=32000)
    explanation: str = Field(default='', max_length=2000)


def identity_reference(store, profile, reference):
    identifier = profile.get('identity_reference_job_id')
    if not identifier:
        return reference
    path = store.directory / 'image-jobs' / str(UUID(identifier)) / 'reference.png'
    if not path.is_file():
        raise GenerationError('原始产品参考图文件缺失，未改用其他素材或重新绘制。')
    return path.read_bytes()


def read_cache(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def apply_rules(directory, snapshot, context, files, prompt, explanation):
    """Image-only models still receive the chosen skill; no text capability is assumed."""
    final = prompt + '\n\n本次适用的制作规范（用户明确要求优先，接口模型和参数由用户配置）：\n' + context
    (directory / 'skill-workflow.json').write_text(json.dumps({'skill': snapshot, 'prompt': final,
        'input_prompt': prompt, 'files': files, 'planning_method': 'rules',
        'planning_note': explanation, 'text_model': ''}, ensure_ascii=False, indent=2), encoding='utf-8')
    return final


def prepare(store, owner, profile: dict, directory: Path, prompt: str, reference: bytes | None) -> str:
    # Lazy import keeps the image queue and agent tools on the same adapters.
    from app.agent_runtime import _chat, _vision, AgentError
    snapshot = profile['skill_workflow']
    experiences = profile.get('drawing_experience', {}).get('direct', [])
    if experiences:
        prompt += '\n\n人工确认的产品作图经验（仅适用于本次用途，不是产品事实，不覆盖本轮明确要求）：\n' + '\n'.join(item['guidance'] for item in experiences)
    try:
        base_url, key, model = store.resolve_text(owner)
    except HTTPException as error:
        raise GenerationError(str(error.detail)) from None
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'input-prompt.txt').write_text(prompt, encoding='utf-8')
    connection = store.get(owner)
    unified = bool(connection and connection.get('unified_models'))
    if unified and not connection.get('planning_model_name') and connection.get('capabilities', {}).get('text', {}).get('state') != 'supported':
        context, files = skill_context(store.directory, snapshot)
        return apply_rules(directory, snapshot, context, files, prompt, '文字辅助尚未确认可用，直接应用制作规范；普通文字调用入口仍可使用和验证。')
    reference_hash = hashlib.sha256(reference).hexdigest() if reference else None
    identity = identity_reference(store, profile, reference)
    identity_hash = hashlib.sha256(identity).hexdigest() if identity else None
    observations = ''
    vision_model = ''
    try:
        vision_url, vision_key, vision_model = store.resolve_vision(owner)
    except HTTPException:
        pass
    cache = store.directory / 'creation-cache' / hashlib.sha256(str(owner).encode()).hexdigest()
    cache.mkdir(parents=True, exist_ok=True)
    fingerprint = json.dumps([2, prompt, profile.get('conversation_context'), reference_hash, identity_hash, snapshot, base_url, model,
                              profile['id'], profile['revision'], vision_model, store.parameters(owner, 'text'), store.parameters(owner, 'vision')], sort_keys=True, ensure_ascii=False)
    cache_path = cache / f'{hashlib.sha256(fingerprint.encode()).hexdigest()}.json'
    context_cache = cache_path.with_suffix('.md')
    cached = read_cache(cache_path)
    if cached and (not context_cache.is_file() or not isinstance(cached.get('prompt'), str) or not 0 < len(cached['prompt']) <= 32000):
        cached = None
    if cached:
        document = cached
        final_prompt = document['prompt']
        shutil.copyfile(context_cache, directory / 'skill-context.md')
    else:
        try:
            if reference is not None and vision_model:
                analysis_key = json.dumps([reference_hash, identity_hash, vision_url, vision_model, profile['id'], profile['revision']])
                analysis_path = cache / f'reference-{hashlib.sha256(analysis_key.encode()).hexdigest()}.json'
                analyzed = read_cache(analysis_path)
                observations = analyzed.get('observations', '') if analyzed else ''
                if not observations:
                    try:
                        observations = _vision(vision_url, vision_key, vision_model, reference,
                            '分析待制作素材的可见结构、部件数量、颜色、连接关系与不能确认的细节。有产品身份参考图时优先核对，不能把错误生成的结构当成原产品事实。不要编造尺寸、认证或性能。',
                            reference=identity if identity_hash != reference_hash else None, parameters=store.parameters(owner, 'vision'))[:12000]
                    except AgentError as error:
                        if not unified: raise
                        from app.model_capabilities import evidence, save_evidence
                        save_evidence(store, owner, 'vision', vision_model, evidence(vision_model, False, error.diagnostic, error.message), profile['revision'])
                        observations = '无法自动分析参考图，仅使用用户确认的信息，图片仍作为实际编辑输入。'
                    else:
                        if not observations.strip(): raise GenerationError('参考图分析未返回内容，未提交图片。')
                        analysis_path.write_text(json.dumps({'observations': observations}, ensure_ascii=False), encoding='utf-8')
            instructions = (
                    '你按以下技能规范编写商品图片的完整提示词。只使用用户确认的事实；保留所有明确要求和准确文案。'
                    '用户明确要求改变的颜色、背景或部位以本轮要求为准，其余保留原产品特征。'
                    '只应用本次用途相关条款，不得把规范中的其它示例当成用户要求。不要求用户建目录或执行脚本。'
                    '有参考图时必须基于实际参考图编辑，不得无参考重画。用户选择的模型与请求参数优先；技能里的模型、质量、尺寸和格式仅作建议，不覆盖用户配置。'
                    '技能脚本不可执行，不得假装已经联网、验图或生成图片。'
                    '先根据任务选择适用技能，读取 SKILL.md，再按需读取相关文件。不要只阅读目录就声称使用了技能。'
                    '发现入口要求读取的必要文件不存在时停止，不得绕过必要步骤。'
                    '不要执行脚本，不要修改文件；生成操作将由网站在策划通过后执行。'
                    '完成文件读取和策划后，最终只返回 JSON：{"status":"ready|needs_input","prompt":"完整提示词","explanation":"需要补充时说明"}。'
                    '缺少必须确认的事实时用 needs_input；不要编造。')
            brief = {'requirements': prompt,
                    'purpose': snapshot['purpose'], 'has_edit_reference': reference is not None,
                    'conversation': profile.get('conversation_context'),
                    'request_parameters': profile.get('parameters', {}),
                    'reference_observations': observations or '无自动视觉观察，不能推测图片中未确认的信息。'}
            from app.skill_agent import plan_with_skills
            reply, reading = plan_with_skills(store.engine, store.directory, directory, snapshot, instructions, brief,
                lambda messages, tools: _chat(base_url, key, model, messages, tools, timeout=300, parameters=store.parameters(owner, 'text')))
            if not isinstance(reply, str):
                raise GenerationError('技能策划未返回可识别的提示词，未提交图片。')
            (directory / 'planning-response.txt').write_text(reply, encoding='utf-8')
            text = reply.strip()
            if text.startswith('```') and text.endswith('```'):
                text = text.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
            prepared = PreparedPrompt.model_validate_json(text)
            if prepared.status != 'ready' or not prepared.prompt.strip():
                raise GenerationError(prepared.explanation or '需要补充制作资料，未提交图片。')
            final_prompt = prepared.prompt.strip()
        except AgentError as error:
            if unified:
                from app.model_capabilities import evidence, save_evidence
                save_evidence(store, owner, 'text', model, evidence(model, False, error.diagnostic, error.message), profile['revision'])
            raise GenerationError(error.message, diagnostic=error.diagnostic) from None
        except ValidationError:
            raise GenerationError('技能策划未返回有效的完整提示词，未提交图片。') from None
        route = 'local-edit' if reference is not None else snapshot['purpose'] if snapshot['purpose'] == 'main-image' else 'general'
        checks = lint_prompt(final_prompt, route)
        if any(item['severity'] == 'error' for item in checks):
            (directory / 'prompt-checks.json').write_text(json.dumps(checks, ensure_ascii=False), encoding='utf-8')
            raise GenerationError('提示词检查未通过：' + '；'.join(item['message'] for item in checks if item['severity'] == 'error'))
        document = {'skill': snapshot, 'prompt': final_prompt, 'input_prompt': prompt, **reading,
                    'reference_sha256': reference_hash, 'reference_observations': observations,
                    'text_model': model, 'prompt_checks': checks}
        shutil.copyfile(directory / 'skill-context.md', context_cache)
        cache_path.write_text(json.dumps(document, ensure_ascii=False), encoding='utf-8')
    (directory / 'skill-workflow.json').write_text(json.dumps({**document, 'reused_preparation': bool(cached)}, ensure_ascii=False, indent=2), encoding='utf-8')
    return final_prompt


def review(store, owner, directory: Path, requirements: str, prompt: str, reference: bytes | None, profile=None) -> dict:
    from app.agent_runtime import _vision, AgentError
    try:
        if profile:
            url, key, model = profile['base_url'], store.key(profile['id'], profile['revision']), profile['review_model']
            if not key: raise HTTPException(409, '运行时密钥已失效。')
        else:
            url, key, model = store.resolve_vision(owner)
    except HTTPException:
        pending = {'status': 'uncertain', 'summary': '未配置视觉模型，待人工审核。', 'checks': [],
                   'method': 'manual_pending', 'compared_reference': False}
        (directory / 'automatic-review.json').write_text(json.dumps(pending, ensure_ascii=False, indent=2), encoding='utf-8')
        return pending
    try:
        image = (directory / 'preview.jpg') if (directory / 'preview.jpg').is_file() else directory / 'result.png'
        direction = profile.get('visual_style') if profile else None
        style_review = ('\n本次确认的视觉规范：' + json.dumps(direction, ensure_ascii=False)
            + '\n逐项检查风格、构图、文字密度与可读性；单图不能证明整套构图有变化，标记该项需整套人工检查。') if direction else ''
        raw = _vision(url, key, model, image.read_bytes(), REVIEW_INSTRUCTIONS
                      + '\n用户制作要求：' + requirements + '\n实际提示词：' + prompt + style_review, reference=reference,
                      parameters=profile.get('review_parameters', {}) if profile else store.parameters(owner, 'vision'))
        result = {**parse_review(raw), 'method': 'vision', 'model': model,
                  'compared_reference': reference is not None}
    except (AgentError, GenerationError, OSError) as error:
        raw = getattr(error, 'message', '质检执行失败，请人工检查已有原图。')
        result = {'status': 'uncertain', 'summary': raw, 'checks': [], 'method': 'vision',
                  'model': model, 'compared_reference': False}
    (directory / 'automatic-review.json').write_text(json.dumps({**result, 'raw_response': raw}, ensure_ascii=False, indent=2), encoding='utf-8')
    return result
