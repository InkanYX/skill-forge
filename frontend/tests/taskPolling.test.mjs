import test from 'node:test';
import assert from 'node:assert/strict';
import { startTaskPolling } from '../src/taskPolling.ts';

class Clock {
  tasks = new Map(); sequence = 0;
  set(callback, delay) { const id = ++this.sequence; this.tasks.set(id, { callback, delay }); return id; }
  clear(id) { this.tasks.delete(id); }
  fire(delay) { const entry = [...this.tasks].find(([, task]) => task.delay === delay); assert.ok(entry, `missing timer ${delay}`); this.tasks.delete(entry[0]); entry[1].callback(); }
}
const flush = async () => { await Promise.resolve(); await Promise.resolve(); };
const pending = jobs => jobs.some(job => ['queued', 'running'].includes(job.status));

test('all terminal states, including HTTP 404 failures, stop further reads', async () => {
  for (const status of ['failed', 'unknown', 'cancelled', 'succeeded']) {
    const clock = new Clock(); let reads = 0;
    const poller = startTaskPolling({ scheduler: clock, load: async () => { reads++; return [{ status, http_status: 404 }]; }, pending, onData: () => {}, onError: assert.fail });
    await flush();
    assert.equal(reads, 1); assert.equal(clock.tasks.size, 0);
    poller.stop();
  }
});

test('queued and running jobs refresh, and stop when the final response fails', async () => {
  const clock = new Clock(); const values = ['queued', 'running', 'failed']; const seen = [];
  const poller = startTaskPolling({ scheduler: clock, load: async () => [{ status: values.shift() }], pending, onData: jobs => seen.push(jobs[0].status), onError: assert.fail });
  await flush(); clock.fire(3000); await flush(); clock.fire(3000); await flush();
  assert.deepEqual(seen, ['queued', 'running', 'failed']); assert.equal(clock.tasks.size, 0);
  poller.stop();
});

test('new submissions and manual refresh can restart a stopped poller', async () => {
  const clock = new Clock(); const values = ['failed', 'queued', 'succeeded']; const seen = [];
  const poller = startTaskPolling({ scheduler: clock, load: async () => [{ status: values.shift() }], pending, onData: jobs => seen.push(jobs[0].status), onError: assert.fail });
  await flush(); assert.equal(clock.tasks.size, 0);
  await poller.refresh(); clock.fire(3000); await flush();
  assert.deepEqual(seen, ['failed', 'queued', 'succeeded']); assert.equal(clock.tasks.size, 0);
  poller.stop();
});

test('stopping a hidden or unmounted page aborts a read and ignores stale data', async () => {
  const clock = new Clock(); let resolve; let signal; const seen = [];
  const poller = startTaskPolling({ scheduler: clock, load: value => { signal = value; return new Promise(done => { resolve = done; }); }, pending, onData: value => seen.push(value), onError: assert.fail });
  poller.stop(); assert.equal(signal.aborted, true);
  resolve([{ status: 'queued' }]); await flush();
  assert.deepEqual(seen, []); assert.equal(clock.tasks.size, 0);
});

test('a later manual refresh wins even if an aborted request still resolves', async () => {
  const clock = new Clock(); const resolvers = []; const seen = [];
  const poller = startTaskPolling({ scheduler: clock, load: () => new Promise(resolve => resolvers.push(resolve)), pending, onData: jobs => seen.push(jobs[0].status), onError: assert.fail });
  const refreshed = poller.refresh();
  resolvers[1]([{ status: 'failed' }]); await refreshed;
  resolvers[0]([{ status: 'queued' }]); await flush();
  assert.deepEqual(seen, ['failed']); assert.equal(clock.tasks.size, 0);
  poller.stop();
});

test('read timeouts stop polling and allow explicit retry without task submission', async () => {
  const clock = new Clock(); const errors = [];
  const poller = startTaskPolling({ scheduler: clock, load: signal => new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(new Error('read timeout')))), pending, onData: assert.fail, onError: error => errors.push(error.message) });
  clock.fire(8000); await flush();
  assert.deepEqual(errors, ['read timeout']); assert.equal(clock.tasks.size, 0);
  poller.stop();
});
