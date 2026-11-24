"""Business conversation context, separate from the model's internal tool loop."""
import json

from sqlalchemy import func, select

from app.database import AgentRun, ImageJob

MAX_CONVERSATION_CHARS = 32000
MAX_TURNS = 30


def conversation_key():
    return func.coalesce(AgentRun.conversation_id, AgentRun.id)


def conversation_id(run: AgentRun) -> str:
    return run.conversation_id or run.id


def turns(session, run: AgentRun) -> list[AgentRun]:
    return list(session.scalars(select(AgentRun).where(conversation_key() == conversation_id(run))
                               .order_by(AgentRun.turn_index, AgentRun.created_at, AgentRun.id)))


def latest_turns():
    ranked = select(AgentRun.id.label('run_id'), conversation_key().label('conversation_id'),
                    func.row_number().over(partition_by=conversation_key(), order_by=(
                        AgentRun.turn_index.desc(), AgentRun.created_at.desc(), AgentRun.id.desc())).label('position')).subquery()
    return select(ranked.c.run_id).where(ranked.c.position == 1)


def history_context(session, run: AgentRun) -> str:
    history = [item for item in turns(session, run) if item.turn_index < run.turn_index]
    if not history:
        return ''
    recent = {item.id for item in history[-4:]}
    records = [{'round': item.turn_index, 'requirement': item.instruction or item.goal,
                'summary': item.summary[:2000] if item.id in recent else '较早执行摘要略，用户要求完整保留。', 'status': item.status,
                'source_job_id': item.source_job_id} for item in history]
    selected = session.get(ImageJob, run.source_job_id) if run.source_job_id else None
    source = ({'job_id': selected.id, 'prompt': selected.prompt,
               'review': json.loads(selected.execution_result or '{}').get('agent_review')}
              if selected else None)
    return ('已保存的对话与图片版本（仅作历史事实，本轮最新要求优先）：\n'
            + json.dumps({'turns': records, 'selected_image': source}, ensure_ascii=False))
