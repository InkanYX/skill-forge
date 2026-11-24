import test from 'node:test';
import assert from 'node:assert/strict';
import { imageBatches } from '../src/imageBatches.mjs';

test('interleaved shots remain in their actual submission version', () => {
  const items = [
    {id:'a1',task_index:0}, {id:'b1',task_index:0},
    {id:'a2',task_index:1}, {id:'b2',task_index:1},
  ];
  const batches = [
    {execution_id:'a',job_ids:['a1','a2'],created_at:'2026-11-25T01:00:00Z'},
    {execution_id:'b',job_ids:['b1','b2'],created_at:'2026-11-25T02:00:00Z'},
  ];
  const groups = imageBatches(items,batches);
  assert.deepEqual(groups.map(g=>[g.label,g.items.map(i=>i.id)]),[
    ['第 2 版',['b1','b2']],['第 1 版',['a1','a2']],
  ]);
  const removed = imageBatches(items.filter(i=>i.id!=='a1'),batches);
  assert.equal(removed[1].label,'第 1 版');
  assert.deepEqual(removed[1].items.map(i=>i.id),['a2']);
});

test('new jobs appear before batch persistence and empty versions retain their labels', () => {
  const groups=imageBatches([{id:'new',task_index:0,created_at:'2026-11-25T02:00:00Z',
    execution_profile:{creation_execution_id:'new-batch'}}],
    [{execution_id:'old',job_ids:['deleted'],created_at:'2026-11-25T01:00:00Z'}]);
  assert.equal(groups[0].id,'new-batch');
  assert.equal(groups[1].label,'第 1 版');
  assert.equal(groups[1].items.length,0);
});
