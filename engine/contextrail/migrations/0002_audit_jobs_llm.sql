-- 0002_audit_jobs_llm: hash-chained audit, Postgres job queue, LLM call ledger (CLAUDE.md §6, §11, D-003).
-- P7 everything leaves a receipt: the audit table is append-only at the database level. UPDATE, DELETE and
-- TRUNCATE are rejected by triggers, so tampering needs DDL (visible) rather than a quiet row edit.
-- hash = sha256(prev_hash || canonical_json(event, payload, at)) is computed in Python (audit/chain.py);
-- the first row's prev_hash is 'GENESIS'.

create table audit (
  seq        bigserial primary key,
  run_id     uuid references runs(id),
  event      text not null,
  payload    jsonb not null default '{}'::jsonb,
  prev_hash  text not null,
  hash       text not null unique check (hash ~ '^[0-9a-f]{64}$'),
  at         timestamptz not null default now()
);
create index audit_run_idx on audit (run_id, seq);

create function audit_is_append_only() returns trigger language plpgsql as $$
begin
  raise exception 'audit is append-only (% refused)', tg_op using errcode = 'insufficient_privilege';
end $$;

create trigger audit_no_update before update or delete on audit
  for each row execute function audit_is_append_only();
create trigger audit_no_truncate before truncate on audit
  for each statement execute function audit_is_append_only();

create table jobs (
  id            bigserial primary key,
  kind          text not null,                -- 'rail.run' | 'approval.deadline' | 'approval.chase' | 'door.update' ...
  payload       jsonb not null default '{}'::jsonb,
  run_at        timestamptz not null default now(),
  attempts      int not null default 0,
  max_attempts  int not null default 5,
  locked_until  timestamptz,
  done          boolean not null default false,
  last_error    text,
  dedupe_key    text unique,                  -- optional: enqueue the same logical job once
  created_at    timestamptz not null default now()
);
-- claim_job: where not done and run_at <= now() and (locked_until is null or locked_until < now())
create index jobs_ready_idx on jobs (run_at) where not done;

create table llm_calls (
  id             bigserial primary key,
  run_id         uuid references runs(id),
  stage          text,
  model          text not null,
  tier           text not null check (tier in ('T1','T2','T3','T4')),
  replay         boolean not null default false,
  input_tokens   int,
  output_tokens  int,
  cost_usd       numeric(10,6) not null default 0,
  latency_ms     int,
  outcome        text not null default 'ok' check (outcome in ('ok','failover','error','budget_refused')),
  error          text,
  at             timestamptz not null default now()
);
create index llm_calls_run_idx on llm_calls (run_id);
