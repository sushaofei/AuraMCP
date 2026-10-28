const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const policy = { allowed_tenants: ['tenant'], allowed_users: ['user', 'other'], dataset: 'records', model_version: 'v1' };
const sandbox = { module: { exports: {} }, require: name => name === 'fs' ? {
  readFileSync: path => path.endsWith('source.json') ? JSON.stringify(policy) : 'test-key'
} : require(name) };
vm.runInNewContext(fs.readFileSync(__dirname + '/cube.js', 'utf8'), sandbox);
const config = sandbox.module.exports;
const securityContext = { tenant_id: 'tenant', user_id: 'user', dataset: 'records', model_version: 'v1', iat: 1 };
test('API scopes receive securityContext directly and exclude SQL', () => {
  assert.deepEqual(Array.from(config.contextToApiScopes(securityContext)), ['meta', 'data']);
  assert.throws(() => config.contextToApiScopes({ ...securityContext, tenant_id: 'denied' }));
  assert.throws(() => config.contextToApiScopes({ ...securityContext, model_version: 'v2' }));
});
test('cache identity is stable across token renewal and isolated across users', () => {
  const id = config.contextToOrchestratorId({ securityContext });
  assert.equal(id, config.contextToOrchestratorId({ securityContext: { ...securityContext, iat: 2 } }));
  assert.notEqual(id, config.contextToOrchestratorId({ securityContext: { ...securityContext, user_id: 'other' } }));
  assert.throws(() => config.queryRewrite({}, { securityContext: { ...securityContext, user_id: 'denied' } }));
});
