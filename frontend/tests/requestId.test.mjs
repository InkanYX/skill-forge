import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { createRequestId } from '../src/requestId.ts';

function withCrypto(value, callback) {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'crypto');
  Object.defineProperty(globalThis, 'crypto', { configurable: true, value });
  try { callback(); }
  finally { Object.defineProperty(globalThis, 'crypto', descriptor); }
}

test('uses the native UUID method with its Crypto receiver when available', () => {
  const native = { randomUUID() { assert.equal(this, native); return 'native-uuid'; } };
  withCrypto(native, () => assert.equal(createRequestId(), 'native-uuid'));
});

test('LAN HTTP without randomUUID still produces distinct valid UUID v4 request IDs', () => {
  const getRandomValues = globalThis.crypto.getRandomValues.bind(globalThis.crypto);
  withCrypto({ getRandomValues }, () => {
    const ids = Array.from({ length: 1000 }, () => createRequestId());
    assert.equal(new Set(ids).size, ids.length);
    for (const id of ids) assert.match(id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  });
});

test('fallback sets UUID version and variant bits and never uses weak randomness', () => {
  withCrypto({ getRandomValues: bytes => bytes.fill(255) }, () => {
    assert.equal(createRequestId(), 'ffffffff-ffff-4fff-bfff-ffffffffffff');
  });
  withCrypto(undefined, () => assert.throws(createRequestId, /不支持安全随机数/));
});

test('UI callers use the LAN-compatible helper instead of the secure-context-only API', () => {
  const root = new URL('../src/', import.meta.url);
  for (const entry of readdirSync(root, { recursive: true })) {
    if (!/\.tsx?$/.test(entry) || entry === 'requestId.ts') continue;
    assert.doesNotMatch(readFileSync(new URL(entry.replaceAll('\\', '/'), root), 'utf8'), /\bcrypto\s*(?:\?\.)?\.\s*randomUUID\s*\(/, entry);
  }
});
