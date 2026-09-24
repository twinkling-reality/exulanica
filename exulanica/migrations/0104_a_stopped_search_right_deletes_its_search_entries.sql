-- 0104_a_stopped_search_right_deletes_its_search_entries.sql
-- Stopping a photograph's search right deletes the search entries made from its descriptions.
--
-- The search right is a personal model right (0073) for the embedding role: it lets the caption
-- pass send a photograph's descriptions to the hosted embedding model, whose vectors are the
-- photograph's search entries. Withdrawing it stopped new requests and nothing else, so every
-- vector already made stayed in `embedding` and kept ranking the photograph. The account holder's
-- decision is that stopping it deletes those entries, the same way deleting the photograph does.
--
-- THE WITHDRAWAL WRITES A TOMBSTONE, for 0082's reasons: `purge_job` is anchored on a tombstone,
-- the worker reads its actor and reason there, completion is recorded on it, and "every destroyed
-- byte traces to a tombstone" is an audit property of the whole system. The new scope is
-- `caption_search`, and the sentence it makes true is:
--
--   A CAPTION_SEARCH TOMBSTONE OVER A CAPTURE ERASES THE SEARCH ENTRIES MADE FROM THAT CAPTURE'S
--   DESCRIPTIONS, AND THE CAPTURE, ITS DESCRIPTIONS AND ITS OTHER RIGHTS SURVIVE BY DESIGN.
--
-- The descriptions belong to the description right (the vision role), which this does not touch,
-- so the photograph is still found by the words of its own description, a match made in this
-- database. Every scope test in this schema is an inclusion test on a named value (0082 measured
-- six and read the rest; `asset_tombstone_capture` and `tombstone_blocks_capture` name
-- 'workspace', 'capture' and 'interval'), so the new value deletes nothing else and makes no
-- other right stop being current.
--
-- WHAT IS ERASED is recorded in `tombstone_embedding_target` and queued in `purge_job` by the
-- tombstone's own insert, as 0044 does for a deleted capture, so an offline restore that replays
-- the tombstone runs the cascade again. `caption_vector_purge_is_authorized` already authorizes a
-- vector recorded there for its tombstone, whatever the scope, so the purge role needs nothing new.
--
-- ANOTHER CURRENT RIGHT KEEPS WHAT IT COVERS. A vector made by a model that another current
-- search right still covers for the same photograph is not erased: the account holder still lets
-- that model index that photograph, and erasing the vector would only be undone by the next pass
-- under the right that stands, at the cost of a model call. The drawer's stop ends every current
-- right of the role over the photograph, so stopping "Search index" erases every entry; a right
-- withdrawn alone through the API while another covers the same model leaves a tombstone with no
-- target, and the entries go when the last covering right stops. An expiry is not a stop and
-- writes nothing, as in 0082.
--
-- A RESULT THAT ARRIVES AFTER THE STOP IS REFUSED. The caption pass holds no transaction while
-- the model runs, so a call allowed when it left can return after the stop committed. The vector
-- insert already takes 0044's per-workspace lifecycle lock, which the tombstone insert takes too;
-- the replaced guard below then refuses a span vector for a capture a caption_search tombstone
-- covers when no current search right covers the capture and the vector's model. 0044's own
-- refusal of an id recorded as a target is kept for every other scope and not for this one: a
-- vector id is a digest of the capture, text and model, so the same id comes back when the
-- account holder grants the right again, and that grant must be able to index the photograph.
--
-- WHAT THIS DOES NOT DO, said plainly. The purge is as prompt as the purge worker: between the
-- stop and the worker's pass the entries still exist and the search still ranks them, exactly as
-- for a deleted photograph's vectors. And a backup restored from before the stop holds the right
-- as current; replaying this tombstone then erases nothing that right covers, because what the
-- cascade reads is whether a right still covers the model, and the backup says one does.
--
-- NOTHING IN THIS FILE USES THE NEW VALUE AS AN ENUM, for 0082's measured reason: every reference
-- is inside a plpgsql body or compares `scope::text`.

begin;
select pg_advisory_xact_lock(119622309);

alter type tombstone_scope add value if not exists 'caption_search';

-- ------------------------------------------------------------------------------------------------
-- Whether a current search right still lets this model index this photograph
-- ------------------------------------------------------------------------------------------------
-- Every search right over the capture naming the model, at any destination, asked through 0073's
-- own currency predicate, so "current" means here what it means to `require_model_right`.
create function caption_search_right_covers(p_workspace uuid, p_capture uuid, p_model text)
returns boolean
language plpgsql volatile as $fn$
begin
  return exists (
    select 1 from personal_model_right r
     where r.workspace_id = p_workspace
       and r.capture_id = p_capture
       and r.model_role = 'embedding'
       and r.model_id = p_model
       and personal_model_right_allows(p_workspace, r.right_id, p_capture, r.model_provider,
                                       r.model_role, r.model_id, r.model_revision,
                                       r.destination, clock_timestamp()));
end $fn$;

-- ------------------------------------------------------------------------------------------------
-- The withdrawal writes the tombstone
-- ------------------------------------------------------------------------------------------------
-- By trigger, never by a caller, for 0082's reason: an erasure a caller must remember to ask for
-- is missing on the withdrawal that matters, and `withdraw_model_right` is not the only way
-- `withdrawn_at` can be set. 0073's immutability trigger lets `withdrawn_at` change exactly once,
-- from null, so this fires once per right.
create function tg_caption_search_right_withdrawn_erases() returns trigger
language plpgsql as $fn$
begin
  if new.model_role <> 'embedding' or old.withdrawn_at is not null
     or new.withdrawn_at is null then
    return new;
  end if;
  perform assert_workspace_context(new.workspace_id);
  insert into tombstone (workspace_id, scope, capture_id, requested_by, effective_at, reason)
  values (new.workspace_id, 'caption_search', new.capture_id, new.withdrawn_by, new.withdrawn_at,
          'a search right over this photograph was stopped');
  return new;
end $fn$;

create trigger tg_caption_search_right_withdrawn_erases
  after update on personal_model_right
  for each row execute function tg_caption_search_right_withdrawn_erases();

-- ------------------------------------------------------------------------------------------------
-- What a caption_search tombstone erases
-- ------------------------------------------------------------------------------------------------
-- The span vectors made from this capture's photograph, found as 0044 finds them, except those
-- whose model a current search right still covers. The target rows are the recorded set the purge
-- authorization reads, and the jobs are the queue the worker drains.
create function tg_caption_search_tombstone_targets() returns trigger
language plpgsql as $fn$
begin
  if new.scope::text <> 'caption_search' then
    return new;
  end if;
  insert into tombstone_embedding_target (workspace_id, tombstone_id, embedding_id)
  select new.workspace_id, new.tombstone_id, e.embedding_id
    from embedding e
   where e.workspace_id = new.workspace_id
     and e.ref_type = 'span'
     and exists (select 1 from evidence_span s join capture c
                   on c.workspace_id = s.workspace_id and c.blob_sha256 = s.blob_sha256
                  where s.workspace_id = e.workspace_id and s.span_id = e.ref_id
                    and c.capture_id = new.capture_id)
     and not caption_search_right_covers(new.workspace_id, new.capture_id, e.model_ref);
  insert into purge_job (workspace_id, tombstone_id, target_kind, target_ref)
  select workspace_id, tombstone_id, 'embedding', embedding_id::text
    from tombstone_embedding_target
   where tombstone_id = new.tombstone_id and workspace_id = new.workspace_id
  on conflict (tombstone_id, target_kind, target_ref) do nothing;
  return new;
end $fn$;

create trigger tg_caption_search_tombstone_targets
  after insert on tombstone
  for each row execute function tg_caption_search_tombstone_targets();

-- ------------------------------------------------------------------------------------------------
-- The vector insert guard, replaced
-- ------------------------------------------------------------------------------------------------
-- 0044's body, with its target refusal narrowed to targets of other scopes, and the refusal of a
-- result that arrives after a stop added after the lock, where the tombstone insert serializes
-- with it.
create or replace function tg_caption_vector_lifecycle_lock() returns trigger
language plpgsql as $fn$
begin
  perform assert_workspace_context(new.workspace_id);
  perform pg_advisory_xact_lock(hashtextextended(
    'caption-vector-lifecycle:' || new.workspace_id::text, 0));
  if tg_table_name <> 'tombstone' then
    if exists (select 1 from tombstone_embedding_target d
                 join tombstone t on t.workspace_id = d.workspace_id
                                 and t.tombstone_id = d.tombstone_id
               where d.workspace_id = new.workspace_id and d.embedding_id = new.embedding_id
                 and t.scope::text <> 'caption_search') then
      perform tombstone_refuse('embedding');
    end if;
    if new.ref_type = 'span' and exists (
         select 1 from evidence_span s
           join capture c on c.workspace_id = s.workspace_id and c.blob_sha256 = s.blob_sha256
           join tombstone t on t.workspace_id = c.workspace_id and t.capture_id = c.capture_id
          where s.workspace_id = new.workspace_id and s.span_id = new.ref_id
            and t.scope::text = 'caption_search'
            and t.effective_at <= clock_timestamp()
            and not caption_search_right_covers(new.workspace_id, c.capture_id,
                                                new.model_ref)) then
      perform tombstone_refuse('embedding');
    end if;
  end if;
  return new;
end $fn$;

commit;
