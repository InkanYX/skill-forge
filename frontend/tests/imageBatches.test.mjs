import test from 'node:test';
import assert from 'node:assert/strict';
import { imageBatches } from '../src/imageBatches.mjs';

test('removed versions do not renumber remaining versions',()=>{
  const groups=imageBatches([], [{execution_id:'v3',job_ids:[],created_at:'3',version_number:3}]);
  assert.equal(groups[0].label,'第 3 版');
});

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

test('retries stay in the original slot and history never becomes another version or export image', () => {
  const items = [
    {id:'a',task_index:0,status:'failed'}, {id:'b',task_index:1,status:'succeeded'},
    {id:'c',task_index:2,status:'succeeded'}, {id:'a1',task_index:3,status:'failed'},
    {id:'a2',task_index:4,status:'succeeded'},
  ];
  const batches = [
    {execution_id:'v1',job_ids:['a2','b'],retry_history:{a2:['a','a1']},created_at:'1'},
    {execution_id:'v2',job_ids:['c'],created_at:'2'},
  ];
  const groups = imageBatches(items, batches);
  assert.equal(groups.length,2);
  assert.equal(groups[1].label,'第 1 版');
  assert.deepEqual(groups[1].items.map(i=>i.id),['a2','b']);
  assert.deepEqual(groups[1].history.map(i=>i.id),['a','a1']);
  const deleted = imageBatches(items.filter(i=>i.id!=='a2'), batches);
  assert.deepEqual(deleted[1].items.map(i=>i.id),['b']);
  assert.equal(deleted.length,2); // Deleted current images must not resurrect failed ancestors.
});
