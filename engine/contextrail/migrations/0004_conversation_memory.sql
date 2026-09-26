-- Bounded, expiring conversational pointers. No raw door messages or decisions live here.
-- The audit chain and sealed case file remain the sources of truth.
create table conversation_memory (
  id          bigint generated always as identity primary key,
  channel     text not null check (channel in ('slack','teams','email','voice','freshservice','mcp')),
  person_id   text not null references identity_map(person_id) on delete cascade,
  thread_key  text not null check (length(thread_key) = 64),
  role        text not null check (role in ('user','assistant')),
  summary     text not null check (length(summary) <= 512),
  run_id      uuid references runs(id) on delete cascade,
  audit_seqs  bigint[] not null default '{}',
  created_at  timestamptz not null default now(),
  expires_at  timestamptz not null
);
create index conversation_memory_scope_idx
  on conversation_memory (person_id, channel, thread_key, id desc);
create index conversation_memory_expiry_idx on conversation_memory (expires_at);
