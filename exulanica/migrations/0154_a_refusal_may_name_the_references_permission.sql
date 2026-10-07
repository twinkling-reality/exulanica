-- 0154_a_refusal_may_name_the_references_permission.sql
-- A recorded route refusal may name the references.request permission.
--
-- Migration 0061 records each refused route in route_permission_refusal, its missing permissions
-- held to the closed list of permission names a token can be granted. The permission vocabulary
-- gains references.request (exulanica/api/permissions.py): asking a web source for reference notes,
-- which spends the operator's source credits and binds the person asking to the source's acceptable
-- use policy. The list also carries door.grant, the permission lane BRIDGE's door adds (pending as
-- its migration 0149, which then no longer restates this constraint), so the two land in either
-- order without either list dropping the other's name. The one change is that list, restated with
-- both names and two more permitted in a refusal; nothing a recorded row relied on is dropped.
begin;
select pg_advisory_xact_lock(119622309);

alter table route_permission_refusal
  drop constraint route_permission_refusal_missing_permissions_check;
alter table route_permission_refusal
  add constraint route_permission_refusal_missing_permissions_check check(
    array_ndims(missing_permissions)=1
    and cardinality(missing_permissions) between 1 and 16
    and array_position(missing_permissions, null) is null
    and missing_permissions <@ array[
      'admission.read','admission.write','consent.read','consent.write','deletion.write',
      'door.grant','intake.write','library.read','library.write','model.invoke','operations.read',
      'operations.write','references.request','tiles.materialise','world.read','world.write'
    ]::text[]
  );

commit;
