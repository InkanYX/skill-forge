"""Progressive skill loading using Deep Agents middleware and LangGraph's agent loop.

Only read tools are exposed. Image requests remain in the existing deduplicated worker.
The provider adapter deliberately reuses our pinned HTTP client and redacted errors.
"""
from __future__ import annotations

import json
import hashlib
import re
import shutil
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from threading import RLock
from typing import Any

import yaml
from deepagents.backends import FilesystemBackend
from deepagents.backends.protocol import ReadResult
from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.skills import SkillsMiddleware
from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, convert_to_openai_messages
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from langsmith import tracing_context
from langgraph.errors import GraphRecursionError
from pydantic import PrivateAttr
from sqlalchemy.orm import Session

from app.database import SkillVersion
from app.image_provider import GenerationError
from app.skill_packages import version_root
from app.skill_store import TEXT_SUFFIXES, _read_capped, parse_frontmatter, safe_join, content_fingerprint, file_entries, ImportRejected

MAX_CALLS = 20
MAX_READ_CHARS = 160000


class ProviderModel(BaseChatModel):
    """No credentials in serializable model fields, checkpoints, or traces."""
    _invoke_provider: Any = PrivateAttr()
    _calls: int = PrivateAttr(default=0)

    def __init__(self, invoke_provider):
        super().__init__()
        self._invoke_provider = invoke_provider

    @property
    def _llm_type(self):
        return 'skill-forge-provider'

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        return self.bind(tools=[convert_to_openai_tool(item) for item in tools])

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self._calls += 1
        if self._calls > MAX_CALLS:
            raise GenerationError('技能读取达到执行上限，未提交图片请求。')
        reply = self._invoke_provider(convert_to_openai_messages(messages), kwargs.get('tools'))
        calls = []
        for item in reply.get('tool_calls') or []:
            if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id']:
                raise GenerationError('模型返回了无效工具调用标识，未提交图片请求。')
            function = item.get('function', {})
            if not isinstance(function, dict) or not isinstance(function.get('name'), str):
                raise GenerationError('模型返回了无效工具名称，未提交图片请求。')
            try:
                arguments = json.loads(function.get('arguments') or '{}')
                if not isinstance(arguments, dict):
                    raise ValueError()
            except (ValueError, TypeError):
                raise GenerationError('模型返回了无效工具参数，未提交图片请求。') from None
            calls.append({'id': item.get('id'), 'name': function.get('name', ''), 'args': arguments})
        content = reply.get('content') or ''
        if not isinstance(content, (str, list)):
            raise GenerationError('模型返回内容格式无效，未提交图片请求。')
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content, tool_calls=calls))])


class ReadOnlySkills(FilesystemBackend):
    def __init__(self, root, entries):
        super().__init__(root_dir=root, virtual_mode=True, max_file_size_mb=2)
        self.entries = entries
        self.reads = []
        self.read_chars = 0
        self.contexts = []
        self._read_lock = RLock()

    def note(self, path, content, offset=0, method='read_file'):
        with self._read_lock:
            self._record(path, content, offset, method)

    def _record(self, path, content, offset, method):
        self.read_chars += len(content)
        if self.read_chars > MAX_READ_CHARS:
            raise GenerationError('本次技能读取内容超过上限，请缩小技能范围后重试。')
        source = self.entries.get(path) or next((item for item in self.entries.values() if item.get('source_entry') == path), {})
        self.reads.append({'path': path, 'offset': offset, 'chars': len(content), 'method': method,
                           'sha256': hashlib.sha256(content.encode()).hexdigest(),
                           'skill_id': source.get('skill_id')})
        self.contexts.append(f'\n<!-- {path} / offset={offset} / {method} -->\n{content}')

    def read(self, file_path, offset=0, limit=2000):
        if PurePosixPath(file_path).name.lower() == 'skill.md' and file_path not in self.entries and not any(
                item.get('source_entry') == file_path for item in self.entries.values()):
            return ReadResult(error='该技能不在本次可用范围，请使用技能目录中已列出的技能。')
        if PurePosixPath(file_path).suffix.lower() not in TEXT_SUFFIXES:
            return ReadResult(error='当前只开放技能文本读取；脚本和二进制资源未启用执行。')
        try:
            result = super().read(file_path, offset, min(limit, 2000))
        except (ValueError, OSError):
            result = ReadResult(error='文件路径超出了本次技能资源范围。')
        if not result.error and result.file_data:
            content = result.file_data.get('content', '')
            self.note(file_path, content, offset)
        else:
            self.reads.append({'path': file_path, 'offset': offset, 'error': result.error})
        return result


def _body(text):
    lines = text.lstrip('\ufeff').splitlines()
    if lines and lines[0].strip() == '---':
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == '---'), None)
        if end is not None:
            return '\n'.join(lines[end + 1:])
    return text


def mount_skills(engine, storage: Path, workspace: Path, snapshot: dict):
    catalog = snapshot.get('catalog') or [snapshot['primary'], *snapshot.get('companions', [])]
    entries, aliases = {}, {}
    copied = set()
    with Session(engine) as session:
        for item in catalog:
            version = session.get(SkillVersion, item['version_id'])
            if version is None or version.skill_id != item['skill_id'] or version.content_sha256 != item['sha256']:
                raise GenerationError('技能版本或内容快照不一致，未提交图片请求。')
            root = version_root(storage, item['skill_id'], item['version_id'])
            original = _read_capped(safe_join(root / 'raw', version.entry_path))
            parse_frontmatter(original)  # Fail before any model call for malformed files.
            bundle_meta = root / 'bundle.json'
            if bundle_meta.is_file():
                meta = json.loads(bundle_meta.read_text(encoding='utf-8'))
                bundle_id = meta['bundle_id']
                if not re.fullmatch(r'[0-9a-f]{64}', bundle_id):
                    raise GenerationError('技能资源快照标识无效。')
                bundle = storage / 'skill-bundles' / bundle_id
                relative = meta['skill_root']
                safe_join(bundle, relative)
            else:
                bundle_id, bundle, relative = item['version_id'], root / 'raw', '.'
            destination = workspace / 'bundles' / bundle_id
            if bundle_id not in copied:
                actual = content_fingerprint(file_entries(bundle))
                expected = bundle_id if bundle_meta.is_file() else item['sha256']
                if actual != expected:
                    raise GenerationError('技能资源内容已改变，请重新导入为新版本后再使用。')
                shutil.copytree(bundle, destination)
                copied.add(bundle_id)
            if bundle_meta.is_file():
                original = _read_capped(safe_join(safe_join(bundle, relative), version.entry_path))
            source_path = f'/bundles/{bundle_id}' + (f'/{relative}' if relative != '.' else '')
            alias = 'skill-' + item['skill_id']
            aliases[item['skill_id']] = alias
            entry = f'/skills/{alias}/SKILL.md'
            path = workspace / entry.lstrip('/')
            path.parent.mkdir(parents=True, exist_ok=True)
            header = yaml.safe_dump({'name': alias, 'description': f'{item["name"]}：{item.get("description") or parse_frontmatter(original).get("description", "")}'}, allow_unicode=True)
            content = f'---\n{header}---\n\n原技能名称：{item["name"]}\n原技能目录：{source_path}\n所有参考文件相对于原技能目录定位；可用 ls、glob、grep 查找。\n\n{_body(original)}'
            path.write_text(content, encoding='utf-8')
            entries[entry] = {**item, 'alias': alias, 'source_root': source_path, 'source_entry': source_path + '/' + version.entry_path, 'content': content}
    return entries, aliases


def plan_with_skills(engine, storage, directory, snapshot, instructions, brief, provider):
    directory.mkdir(parents=True, exist_ok=True)
    # Keep virtual filesystem paths short on Windows, independently of job nesting.
    with TemporaryDirectory(prefix='sf-skills-') as temporary:
        try:
            entries, aliases = mount_skills(engine, storage, Path(temporary), snapshot)
        except (ImportRejected, OSError, ValueError, KeyError) as error:
            raise GenerationError(f'技能入口或资源无法读取，请检查完整导入包：{error}') from None
        backend = ReadOnlySkills(temporary, entries)
        pinned = snapshot.get('pinned', [snapshot['primary']['skill_id']])
        for identifier in pinned:
            entry = next((path for path, value in entries.items() if value['skill_id'] == identifier), None)
            if entry is None:
                raise GenerationError('指定技能无法加载，未提交图片请求。')
            backend.note(entry, entries[entry]['content'], method='pinned')
        agent = create_agent(model=ProviderModel(provider), system_prompt=instructions,
            middleware=[FilesystemMiddleware(backend=backend, tools=['ls', 'read_file', 'glob', 'grep'],
                                             tool_token_limit_before_evict=None, human_message_token_limit_before_evict=None),
                        SkillsMiddleware(backend=backend, sources=['/skills/'])])
        result = None
        completed = False
        try:
            with tracing_context(enabled=False):
                result = agent.invoke({'messages': [{'role': 'user', 'content': json.dumps(brief, ensure_ascii=False)}],
                                       'pinned_skills': [aliases[item] for item in pinned]},
                                      {'recursion_limit': MAX_CALLS * 2 + 4})
            used_ids = {entry['skill_id'] for entry in backend.reads if entry.get('skill_id')}
            injected = {message.additional_kwargs.get('skill', {}).get('name') for message in result['messages']}
            if any(aliases[item] not in injected for item in pinned):
                raise GenerationError('指定技能未成功注入，未提交图片请求。')
            if not used_ids:
                raise GenerationError('模型未读取任何制作技能，未提交图片请求。')
            final = result['messages'][-1].content
            if not isinstance(final, str):
                raise GenerationError('技能策划未返回文本结果，未提交图片请求。')
            used = [{key: value for key, value in item.items() if key not in ('content', 'alias', 'source_root', 'source_entry')}
                    for item in entries.values() if item['skill_id'] in used_ids]
            completed = True
            return final, {'used_skills': used, 'files': backend.reads, 'planning_method': 'deepagents'}
        except GraphRecursionError:
            raise GenerationError('技能读取达到步数上限，未提交图片请求。') from None
        finally:
            trace = {'engine': 'deepagents', 'files': backend.reads,
                     'used_skills': [{k: v for k, v in item.items() if k not in ('content', 'alias', 'source_root', 'source_entry')}
                                     for item in entries.values() if any(r.get('skill_id') == item['skill_id'] for r in backend.reads)],
                     'completed': completed}
            (directory / 'skill-read-log.json').write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding='utf-8')
            (directory / 'skill-context.md').write_text('\n'.join(backend.contexts), encoding='utf-8')
