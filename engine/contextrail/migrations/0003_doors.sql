-- 0003_doors: what the four doors plus Freshworks need (CLAUDE.md §6, §13.0, D-005, D-006).

-- Webhooks retry (Workflow Automator up to 4x, Slack 3x, SNS many). The first delivery wins; the rest are no-ops.
create table webhook_dedupe (
  source       text not null check (source in ('freshservice','slack','teams','ses','vobiz','dodo')),
  external_id  text not null,
  run_id       uuid references runs(id),
  received_at  timestamptz not null default now(),
  primary key (source, external_id)
);

-- One person, every door. A decision is accepted only from an identity mapped here (CLAUDE.md §16).
create table identity_map (
  person_id        text primary key,               -- stable internal id, e.g. 'p-anil'
  display_name     text not null,
  email            text unique,
  slack_user_id    text unique,
  teams_aad_id     text unique,
  phone            text unique check (phone is null or phone ~ '^\+[1-9][0-9]{6,14}$'),   -- E.164
  fs_agent_id      text unique,
  fs_requester_id  text unique,
  hris_id          text unique,                    -- e.g. 'W-8841'
  preferred_door   text not null default 'slack' check (preferred_door in ('slack','teams','email','voice')),
  can_approve      boolean not null default false,
  created_at       timestamptz not null default now()
);
create unique index identity_map_email_ci on identity_map (lower(email));

create table receipts (
  run_id        uuid primary key references runs(id),
  summary       text not null,
  body          jsonb not null,
  audit_from    bigint,                            -- audit seq range covered by this receipt
  audit_to      bigint,
  fs_note_id    text,
  fs_record_id  text,
  created_at    timestamptz not null default now()
);

-- Where each card / email / voice prompt for an action lives, so a decision in one door updates all of them.
create table door_messages (
  run_id      uuid not null references runs(id) on delete cascade,
  action_id   text not null default '',          -- '' = the run-level status message
  channel     text not null check (channel in ('slack','teams','email','voice','freshservice')),
  ref         jsonb not null,                     -- slack {channel, ts} | teams {conversation_id, activity_id} | email {message_id} ...
  sent_at     timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  primary key (run_id, action_id, channel)
);
