"""Version slots keep their identity while each retry remains an immutable job."""
from copy import deepcopy


def replace_batch_job(batches, source_id, replacement_id, include_history=False):
    for batch in batches:
        current_id = source_id
        history = batch.get('retry_history', {})
        if include_history and source_id not in batch.get('job_ids', []):
            current_id = next((key for key, ids in history.items() if source_id in ids), source_id)
        if current_id not in batch.get('job_ids', []):
            continue
        index = batch['job_ids'].index(current_id)
        history = batch.setdefault('retry_history', {})
        history[replacement_id] = [*history.pop(current_id, []), current_id]
        batch['job_ids'][index] = replacement_id
        return batch
    return None


def normalize_batches(batches):
    """Fold old retry-only batches into their source version without altering storage."""
    result = []
    pending = []
    for batch in deepcopy(batches):
        if batch.get('retry_source_job_id') and len(batch.get('job_ids', [])) == 1:
            pending.append(batch)
        else:
            result.append(batch)
    # Older records can be returned out of order. Resolve chains by membership.
    while pending:
        unresolved = []
        for batch in pending:
            if replace_batch_job(result, batch['retry_source_job_id'], batch['job_ids'][0], include_history=True) is None:
                unresolved.append(batch)
        if len(unresolved) == len(pending):
            # Preserve orphaned records rather than guessing another version.
            result.extend(unresolved)
            break
        pending = unresolved
    return result


def visible_batches(batches):
    return [{**batch, 'version_number': index + 1} for index, batch in enumerate(normalize_batches(batches))
            if not batch.get('deleted_at')]
