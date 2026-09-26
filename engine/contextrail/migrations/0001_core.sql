-- 0001_core: runs, actions, approvals (CLAUDE.md §6).
-- Principles enforced here, not only in Python:
--   P1 subject_id is a system-of-record ID (never a name) — set only after exact lookup.
--   P4 a REFUSE verdict is terminal: the row can only ever be 'planned' or 'refused'.
--   D-005 approvals PK (run_id, action_id): the first decision from any door wins.

create table runs (
  id              uuid primary key,
  source          text not null check (source in ('freshservice','slack','email','teams','voice','mcp','web')),
  source_ref      text,                               -- ticket id, slack ts, teams conversation id, call id
  request_text    text not null,
  intent          text,                               -- 'access.same_as_peer' | 'onboarding' | 'refund.outage' | 'query' ...
  subject_id      text,
  status          text not null default 'running'
                  check (status in ('running','needs_input','awaiting_approval','partial','done','failed')),
  stage           text,                               -- current rail stage
  capsule         jsonb,
  capsule_digest  text check (capsule_digest is null or capsule_digest ~ '^[0-9a-f]{64}$'),
  requested_by    text,                               -- identity_map.person_id of the requester (for POL-SOD-001)
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create index runs_source_ref_idx on runs (source, source_ref);
create index runs_status_idx on runs (status, updated_at desc);

create table actions (
  id               text not null,
  run_id           uuid not null references runs(id) on delete cascade,
  kind             text not null,                     -- 'grant' | 'revoke' | 'assign_asset' | 'refund' ...
  target           jsonb not null,                    -- system, resource, params
  params_hash      text not null check (params_hash ~ '^[0-9a-f]{64}$'),
  verdict          text not null check (verdict in ('ALLOW','HOLD','REFUSE')),
  rule_id          text,
  clause           text,
  approver         text,                              -- named human for HOLD
  state            text not null default 'planned'
                   check (state in ('planned','awaiting','approved','refused','executed','verified','failed','unknown')),
  idempotency_key  text unique,
  evidence         jsonb,
  expires_at       timestamptz,
  verified_at      timestamptz,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  primary key (run_id, id),
  -- P4: refusals are terminal. No path (approval, retry, bug) may move a REFUSE forward.
  constraint refuse_is_terminal check (verdict <> 'REFUSE' or state in ('planned','refused')),
  -- A verdict always cites its rule; a HOLD always names who must decide.
  constraint verdict_cites_rule check (rule_id is not null and clause is not null),
  constraint hold_names_approver check (verdict <> 'HOLD' or approver is not null),
  -- 'verified' means read back, with a timestamp (P3: a 200 is not done).
  constraint verified_has_timestamp check (state <> 'verified' or verified_at is not null)
);
create index actions_state_idx on actions (run_id, state);

create table approvals (
  run_id       uuid not null,
  action_id    text not null,
  params_hash  text not null check (params_hash ~ '^[0-9a-f]{64}$'),
  approver     text not null,
  decision     text not null check (decision in ('approved','refused')),
  reason       text,
  channel      text not null check (channel in ('slack','teams','email','voice','freshservice','mcp')),
  decided_at   timestamptz not null default now(),
  primary key (run_id, action_id),
  foreign key (run_id, action_id) references actions (run_id, id) on delete cascade
);
