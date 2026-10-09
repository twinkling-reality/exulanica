-- 0185_a_kept_piece_is_its_receipt.sql
-- The kept generated pieces hold each row to its own receipt, a session is registered once,
-- and an output is written neither for an erased workspace nor from the index under another receipt.
--
-- generation_session: one row per session digest. A session's markers and heartbeats in the bucket
-- are named by its digest, so a second registration of the same record would have two rows answer
-- for one session's markers.
-- generated_piece: every column is the receipt's own (variant, request, components, post-process
-- version, the piece's digest and size, and the verdict), and the cache key is computed from three
-- of them as exulanica_pieces.records.cache_key computes it (canonical JSON, keys sorted, no
-- whitespace; the three values are hex digests and a version made of [a-z0-9.-/], so none needs
-- escaping). No row can name a piece its receipt does not: the comparison must be true, so a receipt
-- that lacks a member it compares (an empty object, an array, a request stored by mistake), which
-- makes the comparison null, is refused too.
-- piece_output: an insert for a workspace that has a workspace tombstone is refused as every other
-- erased table refuses it; an output with no batch (answered from the index) must carry the index
-- row's own receipt, piece digest and verdict (within and the checks it was over).
--
-- No table or column is added and no grant changes. The checks are added validated; the rows the
-- worker and the session commands write already meet them. An installation holding a second
-- registration of one session record (the session command registered a record any number of times
-- before this migration) cannot take it: the unique index fails and nothing of the migration is
-- applied. Find one first with
--   select session_sha256 from generation_session group by 1 having count(*) > 1;
-- such rows cannot be deleted (a registration changes only by its one close), and a removed one
-- would leave its batches unfollowed, so an installation holding one needs the operator's own
-- repair before it is upgraded.
begin;
select pg_advisory_xact_lock(119622309);

create unique index generation_session_digest on generation_session (session_sha256);

alter table generated_piece
  add constraint generated_piece_is_its_receipt
    check ((variant = (receipt_canonical::jsonb ->> 'variant')::integer
            and request_sha256 = receipt_canonical::jsonb ->> 'request_sha256'
            and components_sha256 = receipt_canonical::jsonb ->> 'components_sha256'
            and postprocess_version = receipt_canonical::jsonb -> 'postprocess' ->> 'version'
            and piece_sha256 = receipt_canonical::jsonb -> 'output' ->> 'sha256'
            and piece_bytes = (receipt_canonical::jsonb -> 'output' ->> 'bytes')::integer
            and within = (receipt_canonical::jsonb -> 'verdict' ->> 'within')::boolean) is true),
  add constraint generated_piece_cache_key_is_its_parts
    check (cache_key = encode(sha256(convert_to(
      '{"components_sha256":"' || components_sha256 || '","postprocess":"' || postprocess_version
      || '","request_sha256":"' || request_sha256 || '"}', 'UTF8')), 'hex'));

create or replace function tg_piece_output_append_only() returns trigger language plpgsql as $fn$
begin
  if tg_op = 'INSERT' then
    perform assert_workspace_context(new.workspace_id);
    if exists (select 1 from tombstone t
                where t.workspace_id = new.workspace_id and t.scope = 'workspace') then
      perform tombstone_refuse('piece_output');
    end if;
    -- An output answered from the index, with no batch, is the index row's own receipt and verdict.
    if new.piece_batch_id is null and not exists (
         select 1 from generated_piece g
          where g.cache_key = new.cache_key and g.variant = new.variant
            and g.receipt_sha256 = new.receipt_sha256 and g.piece_sha256 = new.piece_sha256
            and g.within = new.within and g.over_checks = new.over_checks) then
      raise exception 'an output answered from the kept pieces is the kept receipt'
        using errcode = '23514';
    end if;
    return new;
  end if;
  raise exception 'a piece output is recorded once and never changed' using errcode = '23514';
end $fn$;

commit;
