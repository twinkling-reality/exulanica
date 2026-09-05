-- 0035_a_withdrawal_reaches_forward.sql
-- A withdrawal that only reaches backwards is defeated by the next ingest.
--
-- Migration 0030 records, on confirmation of an identity link, every derivative that already
-- depends on that person, and an entity tombstone then marks each of those stale. Both halves
-- work and both were verified. What neither covers is the derivative that does not exist yet.
--
-- Measured on the live schema. Withdraw a person, then ingest one more photograph of the same
-- scene: `run_scene_grouping` computes a new group key, so the artifact id (a uuid5 over the
-- stage version, the parameter digest and the group key) is new, the row is an INSERT rather
-- than a conflict, and `tg_record_person_dependencies_from_derived` files a
-- `person_derivative_dependency` row for the withdrawn entity, with basis
-- 'confirmed_identity_link', because `entity_link.state` is still 'confirmed' and nothing in
-- that recorder looks at `entity.deleted_at`. The cascade that would have staled it ran at the
-- tombstone and does not run again. The result is a live, unmarked derivative naming a
-- withdrawn person's capture, written after they withdrew.
--
-- That is the failure `docs/domain-and-evidence-model.md` 6.4 names in its own words: "a
-- generated title naming a person can be invalidated when that person is deleted. Without the
-- recorded set, the name survives its own deletion inside a caption." Here the recorded set is
-- present and correct, and the name survives anyway, because invalidation only ever looked
-- backwards.
--
-- **Stale, not refused.** Refusing the insert would fail the whole ingest for a workspace where
-- somebody has withdrawn, which turns exercising a right into an outage. A derivative may also
-- legitimately serve captures the withdrawn person is not in. `stale` is the word this schema
-- already has for "computed from something that is no longer true", it is what the entity
-- cascade sets, and nothing anywhere sets it back to false, so a stale-on-arrival artifact is
-- invalidated on exactly the same terms as one invalidated by the tombstone itself.
--
-- **Independent of trigger order.** It reads `dep_index` directly rather than the dependency
-- rows 0030's recorder writes, so it does not depend on which AFTER INSERT trigger fires first.
-- The predicate is 0030's, with the same three prefixes.

begin;

select pg_advisory_xact_lock(119622309);

create function tg_withdrawn_person_stales_a_new_derivative() returns trigger
language plpgsql as $fn$
begin
  if new.stale then
    return new;
  end if;
  if exists (
    select 1
      from entity_link l
      join occurrence o on o.workspace_id = l.workspace_id
                       and o.occurrence_id = l.occurrence_id
      join entity e on e.workspace_id = l.workspace_id and e.entity_id = l.entity_id
     where l.workspace_id = new.workspace_id
       and l.state = 'confirmed'
       and e.deleted_at is not null
       and (('entity:' || l.entity_id::text) = any(new.dep_index)
            or ('occurrence:' || l.occurrence_id::text) = any(new.dep_index)
            or ('capture:' || o.capture_id::text) = any(new.dep_index))
  ) then
    update derived_artifact set stale = true where derived_id = new.derived_id;
  end if;
  return new;
end $fn$;

create trigger tg_withdrawn_person_stales_a_new_derivative
  after insert on derived_artifact
  for each row execute function tg_withdrawn_person_stales_a_new_derivative();

comment on column derived_artifact.stale is
  'Computed from something that is no longer true. Set by the entity withdrawal cascade for '
  'derivatives that existed when the tombstone landed, and by '
  'tg_withdrawn_person_stales_a_new_derivative for one written afterwards that names a '
  'withdrawn person''s capture, occurrence or entity in dep_index. Nothing sets it back to '
  'false: a derived artifact is invalidated, never silently regenerated.';

commit;
