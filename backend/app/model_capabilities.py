"""Evidence belongs to one operation, never to a model-name prefix."""
import json
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import ImageConfiguration


def evidence(model, succeeded, diagnostic=None, message=''):
    diagnostic = diagnostic or {}
    code = str(diagnostic.get('error_code', '')).lower()
    unsupported = code in {'unsupported_capability', 'model_not_supported_for_image_generation',
                            'model_not_supported_for_image_edit', 'unsupported_model_for_operation'}
    state = 'supported' if succeeded else 'unsupported' if unsupported else 'error'
    return {'state': state, 'model': model, 'message': message,
            'diagnostic': diagnostic, 'checked_at': datetime.now(timezone.utc).isoformat()}


def save_evidence(store, owner, kind, model, result, revision=None):
    with Session(store.engine) as session, session.begin():
        row = session.scalar(select(ImageConfiguration).where(ImageConfiguration.owner == owner).with_for_update())
        if row is None or (revision and row.revision != revision):
            return
        names = json.loads(row.model_names or '[]')
        expected = row.model_name if names or kind in ('generate', 'edit') else row.text_model_name if kind == 'text' else row.vision_model_name
        if model != expected and model not in names:
            return
        settings = json.loads(row.model_settings or '{}')
        entry = settings.get(model, {})
        values = dict(entry.get('capabilities', {})) if names else json.loads(row.capabilities or '{}')
        values[kind] = result
        entry['capabilities'] = values; settings[model] = entry
        row.model_settings = json.dumps(settings, ensure_ascii=False)
        if model == row.model_name or not names:
            row.capabilities = json.dumps(values, ensure_ascii=False)
