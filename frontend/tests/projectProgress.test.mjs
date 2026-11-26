import test from 'node:test';
import assert from 'node:assert/strict';
import {productionProgress,projectDestination,projectStatus} from '../src/projectProgress.mjs';
const base={id:'plan',kind:'plan',busy:false,documents:{brief:{confirmed_at:null},prompts:null},images:[],batches:[]};
test('next destination follows confirmed content instead of the old stage flag',()=>{
  assert.equal(projectDestination({...base,stage:'images'}),'#/planning?project=plan&stage=brief');
  assert.equal(projectDestination({...base,documents:{brief:{confirmed_at:'now'}}}),'#/planning?project=plan&stage=prompts');
  assert.equal(projectDestination({...base,documents:{prompts:{confirmed_at:'now'}}}),'#/studio?project=plan');
  assert.equal(projectDestination({...base,kind:'product'}),'#/products?project=plan');
});
test('completion evaluates the latest batch without historical failures or retry ancestors',()=>{
  const project={...base,images:[{id:'old',status:'failed'},{id:'retry',status:'succeeded'},{id:'new',status:'succeeded'}],batches:[{job_ids:['old']},{job_ids:['retry','new']}]};
  assert.deepEqual(productionProgress(project),{total:2,succeeded:2,pending:0,failed:0,unknown:0,complete:true});
  assert.equal(projectStatus(project).key,'complete');
});
test('missing records, partial failures and uncertain outcomes cannot appear completed',()=>{
  const project={...base,images:[{id:'ok',status:'succeeded'},{id:'bad',status:'failed'},{id:'uncertain',status:'unknown'}],batches:[{job_ids:['ok','bad','uncertain','missing']}]};
  assert.equal(productionProgress(project).complete,false);assert.equal(projectStatus(project).key,'busy');
  const ended={...project,batches:[{job_ids:['ok','bad','uncertain']}]};
  assert.equal(projectStatus(ended).key,'attention');assert.equal(projectDestination(ended),'#/studio?project=plan');
  assert.equal(projectStatus(base).key,'draft');assert.equal(productionProgress(base).complete,false);
});
