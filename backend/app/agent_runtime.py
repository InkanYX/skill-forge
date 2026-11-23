"""Server-side agent runtime: a bounded tool loop over an OpenAI-compatible text model.

The model never sees credentials and cannot choose the image model or its parameters.
Every action goes through a fixed tool set; the image path is the existing standard
executor, so results are identical to the non-agent flow.
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Thread
from typing import Annotated
from uuid import UUID, uuid4, uuid5

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.agent_tools import count_copy, lint_prompt, qc_checklist, scan_copy, scenario_catalog
from app.authorization import principal, require_edit
from app.database import (AgentArtifact, AgentRun, AgentStep, ImageConfiguration, ImageJob, SkillPackage,
                          SkillVersion, UserAccount)
from app.image_configurations import ImageConfigStore, MODEL
from app.image_jobs import artifact, create_jobs, now, view as job_view
from app.image_provider import GenerationError, MAX_IMAGE, normalize_image, pinned_url
from app.skill_packages import version_root
from app.skill_store import ImportRejected, read_text

MAX_GOAL = 8000
MAX_PROMPT_CHARS = 32000
MAX_STEP_RECORD = 6000
POLL_SECONDS = 2
IMAGE_WAIT_SECONDS = 360
STALE_RUN_SECONDS = 3600


class AgentError(Exception):
    def __init__(self, message: str, uncertain: bool = False):
        super().__init__(message)
        self.message = message
        self.uncertain = uncertain


class Cancelled(Exception):
    pass


def guard(engine, run_id: str) -> None:
    with Session(engine) as session:
        row = session.get(AgentRun, run_id)
        if row is None or row.status == 'cancelled':
            raise Cancelled()


SYSTEM_PROMPT = """你是 Skill Forge 的商品图制作 Agent。你按照已装入的技能规范工作，并调用工具完成从策划到出图的完整流程。

硬性规则（不可更改，也不要在回复里讨论更改）：
1. 图片模型、质量、尺寸、PNG 格式和 no-augment 已由系统固定，你不能选择或建议更换。
2. 只能使用提供的工具。不能读取技能目录以外的文件，不能执行脚本，不能访问网络。
3. 不得编造尺寸、材质、认证、性能、包含物或服务承诺；只使用用户提供或参考图中可确认的事实。
4. 新图用 generate_image；基于已有结果修改用 edit_image。不得在应当编辑时改成无参考重画。
5. 完整提示词必须先写入 write_prompt，再提交出图。
6. 声明图片可交付前，必须调用 view_image 做检查。视觉工具不可用时，只能以“待人工审核”结束，不得假装通过。
7. 结果状态为 unknown 或超时时，不得重新提交同一张图，应先核对已有文件。
8. 达到步数或出图次数上限时必须停止并说明已完成到哪一步。

工作方式：技能规范已经装入本提示词。需要更细的条款时，用 read_skill_file 读取技能文件。完成或无法继续时调用 finish。"""

TOOLS = [
    {'type': 'function', 'function': {
        'name': 'read_skill_file', 'description': '读取当前技能包中的文本文件，单次最多 20000 字符。脚本与二进制文件不可读。',
        'parameters': {'type': 'object', 'properties': {
            'path': {'type': 'string', 'description': '技能目录内的相对路径'},
            'offset': {'type': 'integer', 'description': '起始字符位置，默认 0'},
            'limit': {'type': 'integer', 'description': '本次最多读取字符数，最大 20000'}},
            'required': ['path']}}},
    {'type': 'function', 'function': {
        'name': 'write_prompt', 'description': '把最终完整的图片提示词保存为 UTF-8 文件，返回 prompt_id。',
        'parameters': {'type': 'object', 'properties': {
            'name': {'type': 'string', 'description': '简短名称，例如 主图-v1'},
            'content': {'type': 'string', 'description': '完整提示词'}},
            'required': ['content']}}},
    {'type': 'function', 'function': {
        'name': 'generate_image', 'description': '使用已保存的 prompt_id 生成一张新图。系统固定使用标准图片规则。',
        'parameters': {'type': 'object', 'properties': {
            'prompt_id': {'type': 'string'},
            'use_reference': {'type': 'boolean', 'description': '是否把用户上传的参考图作为编辑输入'}},
            'required': ['prompt_id']}}},
    {'type': 'function', 'function': {
        'name': 'edit_image', 'description': '基于本次任务中已完成的一张图进行修改，自动把该图作为编辑参考。',
        'parameters': {'type': 'object', 'properties': {
            'prompt_id': {'type': 'string'},
            'source_job_id': {'type': 'string', 'description': '要修改的已完成图片任务 ID'}},
            'required': ['prompt_id', 'source_job_id']}}},
    {'type': 'function', 'function': {
        'name': 'view_image', 'description': '让视觉模型查看某张已完成图片的轻量预览，并回答你的质检问题。',
        'parameters': {'type': 'object', 'properties': {
            'job_id': {'type': 'string'},
            'question': {'type': 'string', 'description': '具体检查项，例如 立柱数量是否为 4 根'}},
            'required': ['job_id', 'question']}}},
    {'type': 'function', 'function': {
        'name': 'lint_prompt', 'description': '按技能自带的提示词规则做文本预检，返回错误与警告。',
        'parameters': {'type': 'object', 'properties': {
            'prompt_id': {'type': 'string'},
            'route': {'type': 'string', 'enum': ['general', 'local-edit', 'main-image', 'finished-image']}},
            'required': ['prompt_id']}}},
    {'type': 'function', 'function': {
        'name': 'count_copy', 'description': '按技能内部排版口径统计文案字数。',
        'parameters': {'type': 'object', 'properties': {
            'text': {'type': 'string'}, 'language': {'type': 'string', 'enum': ['zh', 'en']}},
            'required': ['text']}}},
    {'type': 'function', 'function': {
        'name': 'scan_copy', 'description': '扫描成品文案中的占位符、TODO 和内部备注。',
        'parameters': {'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text']}}},
    {'type': 'function', 'function': {
        'name': 'make_checklist', 'description': '生成逐图交付质检表。',
        'parameters': {'type': 'object', 'properties': {'count': {'type': 'integer'}}, 'required': ['count']}}},
    {'type': 'function', 'function': {
        'name': 'read_scenario', 'description': '查询技能自带的场景配方：list 列出全部，show 查看一个。',
        'parameters': {'type': 'object', 'properties': {
            'command': {'type': 'string', 'enum': ['list', 'show']},
            'id': {'type': 'string'}},
            'required': ['command']}}},
    {'type': 'function', 'function': {
        'name': 'finish', 'description': '结束任务并给出总结。完成、无法继续或需要人工审核时调用。',
        'parameters': {'type': 'object', 'properties': {'summary': {'type': 'string'}}, 'required': ['summary']}}},
]


def run_dir(directory: Path, run_id: str) -> Path:
    return directory / 'agent-runs' / run_id


def prompts_dir(directory: Path, run_id: str) -> Path:
    path = run_dir(directory, run_id) / 'prompts'
    path.mkdir(parents=True, exist_ok=True)
    return path


def _bounded(value: str, limit: int = MAX_STEP_RECORD) -> str:
    return value if len(value) <= limit else value[:limit] + '\n…（已截断）'


def _chat(base_url: str, key: str, model: str, messages: list, tools: list | None = None, timeout: float = 120) -> dict:
    try:
        target, headers, extensions = pinned_url(base_url.rstrip('/') + '/chat/completions')
    except GenerationError as error:
        raise AgentError(error.message) from None
    headers['Authorization'] = f'Bearer {key}'
    body = {'model': model, 'messages': messages, 'temperature': 0.2}
    if tools:
        body['tools'] = tools
        body['tool_choice'] = 'auto'
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=8), follow_redirects=False, trust_env=False) as client:
            response = client.post(target, headers=headers, json=body, extensions=extensions)
    except httpx.HTTPError:
        raise AgentError('文字模型连接失败，请检查网络与服务商地址。') from None
    if response.status_code in (401, 403):
        raise AgentError('文字模型鉴权或权限校验失败，任务已停止，未重试。')
    if response.status_code == 404:
        raise AgentError('文字模型接口未找到：需要兼容 /chat/completions 的 OpenAI 接口。')
    if response.status_code == 429:
        raise AgentError('文字模型限流，请稍后重新提交。')
    if response.status_code != 200:
        raise AgentError(f'文字模型返回 HTTP {response.status_code}，任务已停止。')
    try:
        payload = response.json()
        message = payload['choices'][0]['message']
        if not isinstance(message, dict):
            raise ValueError()
        return message
    except (ValueError, KeyError, IndexError, TypeError):
        raise AgentError('文字模型响应格式无法识别。') from None


def _vision(base_url: str, key: str, model: str, image: bytes, question: str) -> str:
    data = base64.b64encode(image).decode('ascii')
    messages = [
        {'role': 'system', 'content': '你是商品图质检员。只根据看到的图片回答，不确定就说不确定。逐项指出是否存在结构、数量、比例、材质、文字或光影问题，并给出通过或返工建议。'},
        {'role': 'user', 'content': [
            {'type': 'text', 'text': question},
            {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{data}'}},
        ]},
    ]
    message = _chat(base_url, key, model, messages)
    content = message.get('content')
    if isinstance(content, list):
        content = '\n'.join(item.get('text', '') for item in content if isinstance(item, dict))
    return str(content or '').strip() or '视觉模型未返回文字结论。'


class Context:
    def __init__(self, engine, directory: Path, configs: ImageConfigStore, run: AgentRun, version: SkillVersion,
                 package: SkillPackage, messages: list, chat=_chat, vision=_vision, wait=None):
        self.engine, self.directory, self.configs = engine, directory, configs
        self.run, self.version, self.package = run, version, package
        self.messages, self.chat, self.vision, self.wait = messages, chat, vision, wait
        self.steps = 0
        self.image_calls = run.image_calls
        self.summary = ''
        self.finished = False
        self.last_call = ''
        self.reference_bytes = None
        self.skill_root = version_root(directory, package.id, version.id) / 'raw'
        self.owner = run.owner_id

    def record(self, kind: str, tool: str, arguments: dict, result: str) -> None:
        self.steps += 1
        with Session(self.engine) as session, session.begin():
            session.add(AgentStep(run_id=self.run.id, step_index=self.steps, kind=kind, tool_name=tool,
                                  arguments=_bounded(json.dumps(arguments, ensure_ascii=False)),
                                  result=_bounded(result), created_at=now()))
            session.execute(update(AgentRun).where(AgentRun.id == self.run.id)
                            .values(steps_count=self.steps, image_calls=self.image_calls, updated_at=now()))

    def _prompt(self, prompt_id: str) -> str:
        try:
            identifier = str(UUID(prompt_id))
        except ValueError:
            raise AgentError('prompt_id 无效。') from None
        path = prompts_dir(self.directory, self.run.id) / f'{identifier}.txt'
        if not path.is_file():
            raise AgentError('提示词不存在，请先调用 write_prompt。')
        return path.read_text(encoding='utf-8')

    def _job(self, job_id: str) -> ImageJob:
        with Session(self.engine) as session:
            row = session.get(ImageJob, str(job_id))
        if row is None:
            raise AgentError('图片任务不存在。')
        if row.agent_run_id != self.run.id and (self.owner is None or row.owner_id != self.owner):
            raise AgentError('只能操作本任务或本人生成的图片。')
        return row

    def _wait(self, job_id: str, wait) -> dict:
        if wait is not None:
            return wait(job_id)
        deadline = time.monotonic() + IMAGE_WAIT_SECONDS
        while True:
            with Session(self.engine) as session:
                row = session.get(ImageJob, job_id)
                status, message = (row.status, row.message) if row else ('missing', '任务丢失')
                run = session.get(AgentRun, self.run.id)
                cancelled = run is None or run.status == 'cancelled'
            if cancelled:
                return {'job_id': job_id, 'status': 'cancelled',
                        'message': '任务已取消；已经提交的图片调用无法撤回。'}
            if status in ('succeeded', 'failed', 'unknown', 'cancelled', 'missing'):
                return {'job_id': job_id, 'status': status, 'message': message}
            if time.monotonic() > deadline:
                return {'job_id': job_id, 'status': 'unknown', 'message': '等待超时，结果待确认；不要重复提交同一张图。'}
            time.sleep(POLL_SECONDS)

    def _submit(self, prompt_id: str, source_job_id: str | None, use_reference: bool) -> dict:
        if self.image_calls >= self.run.max_images:
            raise AgentError(f'已达到出图次数上限（{self.run.max_images}）。请结束任务并说明。')
        prompt = self._prompt(prompt_id)
        if len(prompt) > MAX_PROMPT_CHARS:
            raise AgentError('提示词超过 32000 字符，请精简后重写。')
        try:
            profile = self.configs.snapshot(self.owner, self.run.config_id)
        except HTTPException as error:
            raise AgentError(str(error.detail)) from None
        reference = self.reference_bytes if use_reference and self.reference_bytes else None
        if use_reference and reference is None:
            raise AgentError('本任务没有可用的参考图。')
        request_id = str(uuid5(UUID(self.run.id), f'image-{self.image_calls + 1}'))
        items = create_jobs(self.engine, self.directory, self.run.config_id, MODEL, prompt, 'default', request_id,
                            reference, 1, source_job_id=source_job_id, standard_config=profile,
                            owner_id=self.owner)
        self.image_calls += 1
        job = items[0]
        with Session(self.engine) as session, session.begin():
            row = session.get(ImageJob, job.id)
            row.agent_run_id = self.run.id
        with Session(self.engine) as session, session.begin():
            session.execute(update(AgentRun).where(AgentRun.id == self.run.id)
                            .values(image_calls=self.image_calls, updated_at=now()))
        outcome = self._wait(job.id, self.wait)
        outcome['mode'] = 'edit' if (reference or source_job_id) else 'generate'
        outcome['prompt_chars'] = len(prompt)
        return outcome

    def call(self, name: str, arguments: dict) -> str:
        if len(self.summary) or self.finished:
            raise AgentError('任务已结束。')
        if name == 'read_skill_file':
            try:
                return json.dumps(read_text(self.skill_root, str(arguments.get('path', '')),
                                            int(arguments.get('offset') or 0),
                                            int(arguments.get('limit') or 20000)), ensure_ascii=False)
            except (ImportRejected, OSError, ValueError) as error:
                raise AgentError(str(error)) from None
        if name == 'write_prompt':
            content = str(arguments.get('content') or '')
            if not content.strip():
                raise AgentError('提示词不能为空。')
            if len(content) > MAX_PROMPT_CHARS:
                raise AgentError('提示词超过 32000 字符。')
            identifier = str(uuid4())
            path = prompts_dir(self.directory, self.run.id) / f'{identifier}.txt'
            path.write_text(content, encoding='utf-8')
            with Session(self.engine) as session, session.begin():
                session.add(AgentArtifact(id=identifier, run_id=self.run.id, kind='prompt',
                                          name=str(arguments.get('name') or '')[:200], path=str(path),
                                          sha256=hashlib.sha256(content.encode()).hexdigest(),
                                          size=len(content.encode()), created_at=now()))
            return json.dumps({'prompt_id': identifier, 'chars': len(content)}, ensure_ascii=False)
        if name == 'generate_image':
            return json.dumps(self._submit(str(arguments.get('prompt_id') or ''), None,
                                           bool(arguments.get('use_reference'))), ensure_ascii=False)
        if name == 'edit_image':
            job = self._job(str(arguments.get('source_job_id') or ''))
            if job.status != 'succeeded':
                raise AgentError('只能基于已完成的图片继续修改。')
            return json.dumps(self._submit(str(arguments.get('prompt_id') or ''), job.id, False), ensure_ascii=False)
        if name == 'view_image':
            job = self._job(str(arguments.get('job_id') or ''))
            if job.status != 'succeeded':
                raise AgentError('图片尚未生成完成。')
            preview = artifact(self.directory, job.id, 'preview.jpg')
            if not preview.is_file():
                raise AgentError('预览图不存在，请检查数据目录。')
            try:
                base_url, key, model = self.configs.resolve_vision(self.owner)
            except HTTPException as error:
                raise AgentError(str(error.detail)) from None
            return self.vision(base_url, key, model, preview.read_bytes(), str(arguments.get('question') or '检查这张图是否可以交付。'))
        if name == 'lint_prompt':
            text = self._prompt(str(arguments.get('prompt_id') or ''))
            route = str(arguments.get('route') or 'general')
            if route not in ('general', 'local-edit', 'main-image', 'finished-image'):
                route = 'general'
            return json.dumps(lint_prompt(text, route), ensure_ascii=False)
        if name == 'count_copy':
            return json.dumps({'count': count_copy(str(arguments.get('text') or ''),
                                                   'en' if arguments.get('language') == 'en' else 'zh')}, ensure_ascii=False)
        if name == 'scan_copy':
            return json.dumps(scan_copy(str(arguments.get('text') or '')), ensure_ascii=False)
        if name == 'make_checklist':
            return qc_checklist(int(arguments.get('count') or 1))
        if name == 'read_scenario':
            try:
                result = scenario_catalog(self.skill_root, str(arguments.get('command') or 'list'),
                                          str(arguments.get('id') or ''))
            except (ValueError, OSError, json.JSONDecodeError) as error:
                raise AgentError(str(error)) from None
            return json.dumps(result, ensure_ascii=False)
        if name == 'finish':
            self.summary = str(arguments.get('summary') or '').strip() or '任务结束。'
            self.finished = True
            return json.dumps({'finished': True}, ensure_ascii=False)
        raise AgentError(f'未知工具：{name}')


def execute_run(engine, directory: Path, configs: ImageConfigStore, run_id: str,
                chat=_chat, vision=_vision, wait=None) -> None:
    with Session(engine) as session:
        run = session.get(AgentRun, run_id)
        if run is None or run.status != 'running':
            return
        version = session.get(SkillVersion, run.skill_version_id)
        package = session.get(SkillPackage, run.skill_id)
        if version is None or package is None:
            _complete(engine, run_id, 'failed', '技能版本缺失，任务未执行。')
            return
    compiled_path = version_root(directory, package.id, version.id) / 'compiled' / 'context.md'
    try:
        compiled = compiled_path.read_text(encoding='utf-8')
    except OSError:
        compiled = ''
    try:
        base_url, key, model = configs.resolve_text(run.owner_id)
        vision_model = ''
        try:
            _, _, vision_model = configs.resolve_vision(run.owner_id)
        except HTTPException:
            vision_model = ''
    except HTTPException as error:
        _complete(engine, run_id, 'failed', str(error.detail))
        return
    system = SYSTEM_PROMPT + f'\n\n技能：{package.name}（版本 {version.version_label}）\n\n' + compiled
    reference = run_dir(directory, run_id) / 'reference.png'
    has_reference = reference.is_file()
    if not vision_model:
        system += ('\n\n注意：本任务未配置视觉模型，view_image 不可用。无法自动质检时，'
                   '调用 finish 并在总结中写明“待人工审核”，不要声称已通过检查。')
    messages = [{'role': 'system', 'content': system},
                {'role': 'user', 'content': _goal_prompt(run, has_reference)}]
    context = Context(engine, directory, configs, run, version, package, messages, chat=chat, vision=vision, wait=wait)
    context.reference_bytes = reference.read_bytes() if has_reference else None
    try:
        for _ in range(run.max_steps):
            guard(engine, run_id)
            message = chat(base_url, key, model, messages, TOOLS)
            messages.append({key_: value for key_, value in message.items()
                             if key_ in ('role', 'content', 'tool_calls') and value is not None})
            calls = message.get('tool_calls') or []
            if not calls:
                summary = str(message.get('content') or '').strip() or '模型未返回可执行步骤，任务结束。'
                context.summary = summary
                context.finished = True
                context.record('assistant', '', {}, summary)
                break
            for call in calls:
                function = call.get('function') if isinstance(call, dict) else None
                if not isinstance(function, dict):
                    continue
                name = str(function.get('name') or '')
                try:
                    arguments = json.loads(function.get('arguments') or '{}')
                    if not isinstance(arguments, dict):
                        raise ValueError()
                except ValueError:
                    arguments = {}
                signature = json.dumps([name, arguments], ensure_ascii=False, sort_keys=True)
                if signature == context.last_call:
                    raise AgentError('检测到重复的相同工具调用，任务已停止以避免循环。')
                context.last_call = signature
                guard(engine, run_id)
                result = context.call(name, arguments)
                context.record('tool', name, arguments, result)
                messages.append({'role': 'tool', 'tool_call_id': call.get('id', ''),
                                 'content': result})
                guard(engine, run_id)
                if context.finished:
                    break
            if context.finished:
                break
        else:
            context.summary = f'已达到步数上限（{run.max_steps}），任务停止。'
            context.record('error', '', {}, context.summary)
    except Cancelled:
        _complete(engine, run_id, 'cancelled', '任务已取消。')
        return
    except AgentError as error:
        status = 'unknown' if error.uncertain else 'failed'
        _complete(engine, run_id, status, error.message)
        return
    except GenerationError as error:
        _complete(engine, run_id, 'unknown' if error.uncertain else 'failed', error.message)
        return
    except Exception:
        _complete(engine, run_id, 'unknown', '执行中断或结果无法确认，请核对已有文件；未重复提交。')
        return
    if not context.summary:
        context.summary = '任务结束。'
    _complete(engine, run_id, 'succeeded', context.summary)


def _goal_prompt(run: AgentRun, has_reference: bool) -> str:
    reference = '本任务提供了 1 张已授权参考图，生成时可用 use_reference=true 把参考图作为编辑输入。' if has_reference else '本任务没有参考图。'
    return (f'目标：{run.goal}\n\n{reference}\n\n'
            '请先判断本次是生成新图还是编辑参考图。完整提示词必须先写入 write_prompt。'
            '出图后必须调用 view_image 检查再决定是否交付。')


def _complete(engine, run_id: str, status: str, message: str) -> None:
    with Session(engine) as session, session.begin():
        session.execute(update(AgentRun).where(AgentRun.id == run_id)
                        .values(status=status, summary=message, error='' if status == 'succeeded' else message,
                                updated_at=now(), finished_at=now()))


def process_agent_one(engine, directory: Path, configs: ImageConfigStore) -> bool:
    if engine is None:
        return False
    with Session(engine) as session, session.begin():
        rows = session.scalars(select(AgentRun).where(AgentRun.status == 'queued')
                               .order_by(AgentRun.created_at).limit(20).with_for_update(skip_locked=True))
        selected = None
        for row in rows:
            config = session.get(ImageConfiguration, row.config_id)
            if config is None:
                row.status, row.error, row.updated_at, row.finished_at = 'failed', '图片服务配置已删除，任务未执行。', now(), now()
                continue
            if getattr(configs, 'auth_enabled', False):
                account = session.get(UserAccount, row.owner_id) if row.owner_id else None
                if not account or not account.is_active:
                    row.status, row.error, row.updated_at, row.finished_at = 'cancelled', '所属账号不可用，任务未执行。', now(), now()
                    continue
            if configs.key(row.config_id, config.revision):
                selected = row
                break
            message = '等待运行时密钥，请在个人模型配置中重新填写密钥。'
            if row.error != message:
                row.error = message
        if selected is None:
            return False
        selected.status, selected.error, selected.updated_at = 'running', '', now()
        run_id = selected.id
    execute_run(engine, directory, configs, run_id)
    return True


class AgentWorker:
    def __init__(self, engine, directory: Path, configs: ImageConfigStore):
        self.engine, self.directory, self.configs = engine, directory, configs
        self.stop_event = Event()
        self.thread = Thread(target=self.run, daemon=True)

    def run(self):
        try:
            with Session(self.engine) as session, session.begin():
                session.execute(update(AgentRun).where(AgentRun.status == 'running')
                                .values(status='unknown', error='服务重启，执行中断；结果待确认，未重复提交。',
                                        updated_at=now(), finished_at=now()))
        except Exception:
            # A missing table or transient database error must not kill the worker.
            pass
        while not self.stop_event.is_set():
            try:
                worked = process_agent_one(self.engine, self.directory, self.configs)
            except Exception:
                worked = False
            if not worked:
                self.stop_event.wait(3)

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=2)


class RunInput(BaseModel):
    goal: str = Field(min_length=1, max_length=MAX_GOAL)
    skill_id: UUID
    config_id: UUID
    max_steps: int = Field(default=20, ge=5, le=40)
    max_images: int = Field(default=6, ge=1, le=8)


class ReworkInput(BaseModel):
    instruction: str = Field(min_length=1, max_length=4000)


def run_view(session: Session, row: AgentRun) -> dict:
    steps = session.scalars(select(AgentStep).where(AgentStep.run_id == row.id)
                            .order_by(AgentStep.step_index).limit(200)).all()
    images = session.scalars(select(ImageJob).where(ImageJob.agent_run_id == row.id)
                             .order_by(ImageJob.created_at)).all()
    return {'id': row.id, 'status': row.status, 'goal': row.goal, 'skill_id': row.skill_id,
            'skill_version_id': row.skill_version_id, 'config_id': row.config_id,
            'model_name': row.model_name, 'vision_model_name': row.vision_model_name,
            'steps_count': row.steps_count, 'image_calls': row.image_calls,
            'max_steps': row.max_steps, 'max_images': row.max_images,
            'summary': row.summary, 'error': row.error,
            'created_at': row.created_at, 'updated_at': row.updated_at, 'finished_at': row.finished_at,
            'steps': [{'index': step.step_index, 'kind': step.kind, 'tool': step.tool_name,
                       'arguments': step.arguments, 'result': step.result, 'created_at': step.created_at}
                      for step in steps],
            'images': [job_view(item).model_dump() for item in images]}


def build_agent_router(engine, directory: Path, configs: ImageConfigStore) -> APIRouter:
    router = APIRouter(prefix='/api/agent', tags=['agent'])

    def require_db():
        if engine is None:
            raise HTTPException(503, 'Agent 任务需要配置数据库并执行迁移。')

    def visible_run(run_id: UUID) -> AgentRun:
        with Session(engine) as session:
            row = session.get(AgentRun, str(run_id))
        user = principal.get()
        if row is None or (user and user['role'] != 'admin' and row.owner_id != user['id']):
            raise HTTPException(404, '任务不存在。')
        return row

    @router.post('/runs')
    def create_run(request: Request, payload: Annotated[str, Form(max_length=20000)],
                   reference: Annotated[UploadFile | None, File()] = None):
        require_db()
        try:
            data = RunInput.model_validate_json(payload)
        except ValueError:
            raise HTTPException(422, '任务参数格式无效。') from None
        user = principal.get()
        with Session(engine) as session:
            package = session.get(SkillPackage, str(data.skill_id))
            if package is None or (user is not None and package.source != 'builtin'
                                   and package.owner_id is not None and package.owner_id != user['id']):
                raise HTTPException(404, '技能包不存在。')
            version = session.get(SkillVersion, package.current_version_id) if package.current_version_id else None
            if version is None or version.skill_id != package.id:
                raise HTTPException(422, '该技能包还没有启用的版本，请先在技能库中手动启用。')
            skill_id, version_id = package.id, version.id
        current = configs.get(request.state.image_owner)
        if not current or current['id'] != str(data.config_id):
            raise HTTPException(422, '请先在个人模型配置中保存图片服务。')
        configs.snapshot(request.state.image_owner, str(data.config_id))
        try:
            base_url, key, model = configs.resolve_text(request.state.image_owner)
            vision_model = ''
            try:
                _, _, vision_model = configs.resolve_vision(request.state.image_owner)
            except HTTPException:
                vision_model = ''
        except HTTPException as error:
            raise HTTPException(422, str(error.detail)) from None
        run_id = str(uuid4())
        try:
            content = normalize_image(reference.file.read(MAX_IMAGE + 1)) if reference else None
        except GenerationError as error:
            raise HTTPException(422, error.message) from None
        if content is not None:
            target = run_dir(directory, run_id) / 'reference.png'
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        run = AgentRun(id=run_id, owner_id=request.state.image_owner, skill_id=skill_id,
                       skill_version_id=version_id, config_id=str(data.config_id), status='queued',
                       goal=data.goal.strip(), model_name=model, vision_model_name=vision_model,
                       steps_count=0, image_calls=0, max_steps=data.max_steps, max_images=data.max_images,
                       error='', summary='', created_at=now(), updated_at=now())
        with Session(engine) as session, session.begin():
            session.add(run)
            row = session.get(AgentRun, run_id)
            return run_view(session, row)

    @router.get('/runs')
    def list_runs():
        require_db()
        with Session(engine) as session:
            statement = select(AgentRun).order_by(AgentRun.created_at.desc()).limit(30)
            user = principal.get()
            if user:
                statement = statement.where(AgentRun.owner_id == user['id'])
            return [run_view(session, row) for row in session.scalars(statement)]

    @router.get('/runs/{run_id}')
    def get_run(run_id: UUID):
        require_db()
        visible_run(run_id)
        with Session(engine) as session:
            return run_view(session, session.get(AgentRun, str(run_id)))

    @router.post('/runs/{run_id}/cancel')
    def cancel(run_id: UUID):
        require_db()
        with Session(engine) as session, session.begin():
            row = session.get(AgentRun, str(run_id), with_for_update=True)
            if row is None:
                raise HTTPException(404, '任务不存在。')
            require_edit(row)
            if row.status in ('queued', 'running'):
                row.status, row.error, row.updated_at, row.finished_at = 'cancelled', '任务已取消。', now(), now()
            return run_view(session, row)

    @router.post('/runs/{run_id}/rework')
    def rework(run_id: UUID, data: ReworkInput):
        require_db()
        with Session(engine) as session:
            previous = session.get(AgentRun, str(run_id))
            if previous is None:
                raise HTTPException(404, '任务不存在。')
            require_edit(previous)
            images = list(session.scalars(select(ImageJob).where(ImageJob.agent_run_id == previous.id,
                                                                  ImageJob.status == 'succeeded')))
            hint = ''
            if images:
                hint = '\n\n上一轮已完成的图片任务：' + '、'.join(
                    f'{item.id}（{item.shot_name or item.id[:8]}）' for item in images[:6]) + \
                    '。如需在这些图上修改，用 edit_image 并传入对应 source_job_id。'
            goal = f'{previous.goal}\n\n上一轮结论：{previous.summary or "无"}{hint}\n\n本次补充要求：{data.instruction}'
            if len(goal) > MAX_GOAL:
                goal = goal[:MAX_GOAL]
            run = AgentRun(id=str(uuid4()), owner_id=previous.owner_id, skill_id=previous.skill_id,
                           skill_version_id=previous.skill_version_id, config_id=previous.config_id,
                           status='queued', goal=goal, model_name=previous.model_name,
                           vision_model_name=previous.vision_model_name, steps_count=0, image_calls=0,
                           max_steps=previous.max_steps, max_images=previous.max_images,
                           error='', summary='', created_at=now(), updated_at=now())
            source = run_dir(directory, previous.id) / 'reference.png'
            if source.is_file():
                target = run_dir(directory, run.id) / 'reference.png'
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
            session.add(run)
            session.flush()
            return run_view(session, run)

    @router.get('/runs/{run_id}/prompts/{prompt_id}')
    def get_prompt(run_id: UUID, prompt_id: UUID):
        require_db()
        visible_run(run_id)
        path = prompts_dir(directory, str(run_id)) / f'{prompt_id}.txt'
        if not path.is_file():
            raise HTTPException(404, '提示词不存在。')
        return {'prompt_id': str(prompt_id), 'content': path.read_text(encoding='utf-8')}

    @router.get('/runs/{run_id}/artifacts')
    def list_artifacts(run_id: UUID):
        require_db()
        visible_run(run_id)
        with Session(engine) as session:
            rows = session.scalars(select(AgentArtifact).where(AgentArtifact.run_id == str(run_id))
                                   .order_by(AgentArtifact.created_at)).all()
            return [{'id': row.id, 'kind': row.kind, 'name': row.name, 'size': row.size,
                     'created_at': row.created_at} for row in rows]

    return router
