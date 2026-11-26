from copy import deepcopy

from app.image_batches import normalize_batches, replace_batch_job


def test_legacy_retry_batches_fold_into_original_versions_and_preserve_shots():
    batches = [
        {'execution_id': 'v1', 'job_ids': ['a', 'b'], 'shot_ids': ['hero', 'detail'], 'created_at': '1'},
        {'execution_id': 'v2', 'job_ids': ['c', 'd'], 'created_at': '2'},
        {'execution_id': 'retry1', 'job_ids': ['a1'], 'retry_source_job_id': 'a'},
        {'execution_id': 'retry2', 'job_ids': ['a2'], 'retry_source_job_id': 'a1'},
        {'execution_id': 'retry3', 'job_ids': ['b1'], 'retry_source_job_id': 'b'},
        {'execution_id': 'retry4', 'job_ids': ['a3'], 'retry_source_job_id': 'a'},
    ]
    original = deepcopy(batches)
    normalized = normalize_batches(batches)
    assert batches == original
    assert len(normalized) == 2
    assert normalized[0] == {'execution_id': 'v1', 'job_ids': ['a3', 'b1'],
        'shot_ids': ['hero', 'detail'], 'created_at': '1',
        'retry_history': {'a3': ['a', 'a1', 'a2'], 'b1': ['b']}}
    assert normalized[1] == batches[1]
    assert normalize_batches(normalized) == normalized
    assert replace_batch_job(normalized, 'a', 'stale') is None


def test_missing_legacy_source_is_retained_without_guessing():
    batches = [{'execution_id': 'orphan', 'job_ids': ['r'], 'retry_source_job_id': 'missing'}]
    assert normalize_batches(batches) == batches
