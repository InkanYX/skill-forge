import test from 'node:test';
import assert from 'node:assert/strict';
import { readView, writeView } from '../src/workspaceViewState.ts';

const entries=new Map();
globalThis.sessionStorage={getItem:key=>entries.get(key)??null,setItem:(key,value)=>entries.set(key,value)};

test('list preferences and product searches remain scoped to account and product',()=>{
  writeView('alice','records:product:applied',{query:'庭院',status:'ready'});
  writeView('alice','product:one:plans-query','A+');
  assert.deepEqual(readView('alice','records:product:applied',{}),{query:'庭院',status:'ready'});
  assert.equal(readView('bob','product:one:plans-query',''),'');
  assert.equal(readView('alice','product:two:plans-query',''),'');
  assert.equal(readView('alice','product:one:plans-query',''),'A+');
});

test('scroll positions retain the exact product tab and plan route',()=>{
  writeView('alice','scroll:#/products?project=p&tab=plans',843);
  assert.equal(readView('alice','scroll:#/products?project=p&tab=plans',0),843);
  assert.equal(readView('alice','scroll:#/products?project=p&tab=materials',0),0);
});

test('disabled storage and corrupt JSON do not break navigation',()=>{
  entries.set('skill-forge:view:v1:broken:query','{broken');
  assert.equal(readView('broken','query',''),'');
  const original=globalThis.sessionStorage;
  globalThis.sessionStorage={getItem:()=>{throw Error('blocked');},setItem:()=>{throw Error('blocked');}};
  writeView('memory','query','canopy');
  assert.equal(readView('memory','query',''),'canopy');
  globalThis.sessionStorage=original;
});
