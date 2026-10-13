-- 0194_acting_as_a_being_is_its_own_permission.sql
-- A recorded route refusal may name the being.act permission.
--
-- Migration 0061 records each refused route in route_permission_refusal, its missing permissions
-- held to the closed list of permission names a token can be granted (restated by 0154). The
-- permission vocabulary gains being.act (exulanica/api/permissions.py): starting to play one being
-- of a society, answering for it and giving it back, which asked for world.write until now. A
-- credential that holds world.write and not being.act is refused on those three routes, and the
-- refusal names what it lacks, so the list must admit the name or the refusal could not be
-- recorded.
--
-- The one change is that list, restated with being.act beside the sixteen names it held, and
-- seventeen permitted in one refusal where sixteen were. Every name a recorded row may hold is
-- still in the list and no stored row is rewritten, so no row can fail the new check. The check
-- is validated against the stored rows as it is added, under the table's lock for that moment;
-- the table holds one row for a workspace, an actor and a route refused.
--
-- Apply it before the API that knows being.act starts. The floor records a refusal before it
-- answers, so that API on a schema without this migration cannot record a refusal naming
-- being.act: a credential that edits the world and may not act as a being would be answered 500
-- on the three routes in place of 404. The older API on this schema is unaffected.
--
-- The way back: once a refusal naming being.act is recorded, 0154's list would refuse that row,
-- so the older check cannot be put back without first deciding what becomes of such rows.
--
-- Touches: route_permission_refusal (constraint
-- route_permission_refusal_missing_permissions_check). No table, column, index, trigger,
-- function, grant or policy is added, removed or altered.
begin;
select pg_advisory_xact_lock(119622309);

alter table route_permission_refusal
  drop constraint route_permission_refusal_missing_permissions_check;
alter table route_permission_refusal
  add constraint route_permission_refusal_missing_permissions_check check(
    array_ndims(missing_permissions)=1
    and cardinality(missing_permissions) between 1 and 17
    and array_position(missing_permissions, null) is null
    and missing_permissions <@ array[
      'admission.read','admission.write','being.act','consent.read','consent.write',
      'deletion.write','door.grant','intake.write','library.read','library.write','model.invoke',
      'operations.read','operations.write','references.request','tiles.materialise','world.read',
      'world.write'
    ]::text[]
  );

commit;
