-- Run once in your own Supabase SQL Editor. Existing fitness tables are unchanged.
create table if not exists public.dietmcp_private_state (
  user_id uuid not null references auth.users(id) on delete cascade,
  collection text not null,
  key text not null,
  ciphertext text not null,
  created_at timestamptz not null default now(),
  expires_at timestamptz,
  primary key (user_id, collection, key)
);
alter table public.dietmcp_private_state enable row level security;
revoke all on public.dietmcp_private_state from anon, authenticated;
grant all on public.dietmcp_private_state to service_role;
-- No authenticated/anon policy: backend service key only.
