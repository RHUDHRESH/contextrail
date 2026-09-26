-- 0005_knowledge: curated OKF and receipt chunks for grounded retrieval (T252).
-- Retrieval is evidence for answers only; policy does not read this table.

-- One row per retrievable chunk: a heading-section of a curated OKF page, or one line of a run's receipt.
create table knowledge_chunks (
  id             text primary key,                  -- 'okf:<path>#<slug>' | 'rcpt:<run_id>#<action_id>|summary'
  source         text not null check (source in ('okf', 'receipt')),
  uri            text not null,                     -- where a person finds it: knowledge/<path>#<heading> | run://<id>
  title          text not null,
  heading        text not null default '',
  body           text not null,
  rules          text[] not null default '{}',      -- rule links: the page's rules:, or the action's deciding rule
  clause_of      text[] not null default '{}',      -- rules whose quoted clause is this very section
  tags           text[] not null default '{}',
  run_id         uuid references runs(id) on delete cascade,   -- receipts only; retrieved only for their own run
  audit_seqs     bigint[] not null default '{}',    -- audit rows a receipt chunk is drawn from
  trust          text not null check (trust in ('curated', 'record')),
  last_verified  date,
  content_hash   text not null check (content_hash ~ '^[0-9a-f]{64}$'),
  tsv            tsvector generated always as (
                   setweight(to_tsvector('english', title || ' ' || heading), 'A') ||
                   setweight(to_tsvector('english', body), 'B')) stored,
  indexed_at     timestamptz not null default now(),
  check ((source = 'receipt') = (run_id is not null))
);
create index knowledge_chunks_tsv_idx on knowledge_chunks using gin (tsv);
create index knowledge_chunks_rules_idx on knowledge_chunks using gin (rules);
create index knowledge_chunks_run_idx on knowledge_chunks (run_id) where run_id is not null;
