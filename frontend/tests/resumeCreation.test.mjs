import test from 'node:test';
import assert from 'node:assert/strict';
import { creationLocation, readResume, rememberCreation } from '../src/resumeCreation.ts';

const stored = new Map();
globalThis.localStorage = { getItem: key => stored.get(key) ?? null, setItem: (key, value) => stored.set(key, value) };

test('leaving a creative task for home, lists, or settings keeps its exact stage', () => {
  rememberCreation('member-a', '#/planning?project=plan-a&stage=prompts', 'A+ 策划');
  for (const route of ['#/', '#/library', '#/settings', '#/planning', '#/planning?new=1', '#/planning?view=templates&project=template', '#/studio']) rememberCreation('member-a', route);
  assert.equal(readResume('member-a').route, '#/planning?project=plan-a&stage=prompts');
  assert.equal(readResume('member-a').title, 'A+ 策划');
});

test('bookmarks survive memory-independent storage reads and remain account scoped', () => {
  stored.set('skill-forge:resume:v1:reload', JSON.stringify({ route: '#/studio?task=task-1', title: '生图', label: '图片制作', updatedAt: new Date().toISOString() }));
  assert.equal(readResume('reload').route, '#/studio?task=task-1');
  assert.equal(readResume('different-account'), null);
  stored.set('skill-forge:resume:v1:corrupt', '{broken');
  assert.equal(readResume('corrupt'), null);
});

test('task and source URLs are local allowlisted routes without extra parameters', () => {
  assert.equal(creationLocation('#/studio?task=task-1&key=secret').route, '#/studio?task=task-1');
  assert.equal(creationLocation('#/edit?source=job-1').route, '#/edit?source=job-1');
  assert.equal(creationLocation('https://example.com/?project=1'), null);
  assert.equal(creationLocation('#/studio?run=run-1').route, '#/studio?run=run-1');
});

test('product workspace resumes the selected materials or child-plan tab', () => {
  rememberCreation('product-tabs', '#/products?project=product-1&tab=plans&key=secret', '庭院产品');
  assert.equal(readResume('product-tabs').route, '#/products?project=product-1&tab=plans');
  assert.equal(readResume('product-tabs').label, '该产品的图片策划');
  assert.equal(creationLocation('#/products?project=product-1&tab=materials').route, '#/products?project=product-1&tab=materials');
  assert.equal(creationLocation('#/products?project=product-1&tab=unknown').route, '#/products?project=product-1');
});
