// Replace only after reviewing the existing capability's relation/column allowlist.
cube('source_records', {
  sql: 'SELECT id, area, amount, published_at FROM approved_schema.approved_records',
  public: false,
  measures: {
    count: { type: 'count', description: 'Record count, without project deduplication' },
    amount: { sql: 'amount', type: 'sum', description: 'Sum of non-null values in the source unit' }
  },
  dimensions: {
    id: { sql: 'id', type: 'number', primary_key: true },
    area: { sql: 'area', type: 'string' },
    published_at: { sql: "published_at AT TIME ZONE 'Asia/Shanghai'", type: 'time' }
  }
});
view('records', {
  meta: { model_version: 'records-v1' },
  cubes: [{ join_path: source_records, includes: ['count', 'amount', 'id', 'area', 'published_at'] }],
  // Full approved relation scope only. Add a server-derived row policy before sharing a tenant table.
  access_policy: [{ group: 'semantic_reader', member_level: { includes: '*' }, row_level: { allow_all: true } }]
});
