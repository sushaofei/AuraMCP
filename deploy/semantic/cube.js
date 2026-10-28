// Configuration and model releases are immutable. Only the private deployment contains source data.
const fs = require('fs');
const crypto = require('crypto');
const policy = JSON.parse(fs.readFileSync('/run/config/source.json', 'utf8'));
function scope(context) {
  const s = context.securityContext || {};
  if (!policy.allowed_tenants.includes(s.tenant_id) || !policy.allowed_users.includes(s.user_id) ||
      s.dataset !== policy.dataset || s.model_version !== policy.model_version) {
    throw new Error('Semantic access denied');
  }
  return s;
}
const scopeKey = (context) => {
  const s = scope(context);
  return crypto.createHash('sha256').update(JSON.stringify([s.tenant_id, s.user_id, s.dept_id, s.dataset, s.model_version])).digest('hex');
};
module.exports = {
  apiSecret: fs.readFileSync('/run/secrets/cube_api_secret', 'utf8').trim(),
  jwt: {
    key: fs.readFileSync('/run/secrets/cube_public_key', 'utf8'),
    algorithms: ['RS256'], issuer: ['auramcp-semantic'], audience: 'cube-semantic'
  },
  contextToApiScopes: securityContext => { scope({ securityContext }); return ['meta', 'data']; },
  contextToGroups: context => { scope(context); return ['semantic_reader']; },
  contextToAppId: context => `semantic_${policy.model_version}_${scope(context).tenant_id}`,
  contextToOrchestratorId: context => `semantic_${scopeKey(context)}`,
  queryRewrite: (query, context) => { scope(context); return query; },
  scheduledRefreshTimer: false,
  scheduledRefreshContexts: async () => [],
  driverFactory: () => ({
    type: 'postgres', host: policy.host, port: policy.port, database: policy.database,
    user: policy.user, password: fs.readFileSync('/run/secrets/source_password', 'utf8').trim(),
    ssl: policy.ssl === 'require' ? { rejectUnauthorized: true } : false,
    maxPoolSize: 2, readOnly: true,
    options: "-c default_transaction_read_only=on -c statement_timeout=5000",
    // Read-only and statement timeout are established on every source connection.
    executionTimeout: 5,
  }),
};
