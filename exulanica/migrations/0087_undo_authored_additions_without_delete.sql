-- Undoing an authored addition updates its mutable projection and keeps the append-only edits.
-- The runtime role deliberately has no DELETE privilege, so undo must not remove this row.

begin;

alter table world_alternate_object
  add column addition_undone boolean not null default false,
  add constraint world_alternate_object_undone_addition_is_removed check (
    not addition_undone or (removed and created_edit_id <> last_edit_id)
  );

comment on column world_alternate_object.addition_undone is
  'True only when an undo edit reversed the addition that created this projection row. Readers omit the row, while the row and edit log retain exact history.';

commit;
