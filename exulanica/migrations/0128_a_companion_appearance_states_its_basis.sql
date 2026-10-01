-- 0128_a_companion_appearance_states_its_basis.sql
-- A Companion appearance proposal states what it is drawn from. `evidence` names the world's own
-- evidence by reference id, as every Companion proposal had to before; `authored_design` is a
-- design choice and names none, so a world that holds no evidence can still be given a look
-- through the Companion without a reference nothing was drawn from. Other origins state no basis.
-- The domain holds the same rule (WorldStyleRepository._validate_proposal_provenance). A row
-- written before this column is a Companion proposal drawn from evidence, and satisfies it as is.
begin;
select pg_advisory_xact_lock(119622309);

alter table world_style_proposal
  add column appearance_basis text check (appearance_basis in ('evidence','authored_design'));
alter table world_style_version
  add column appearance_basis text check (appearance_basis in ('evidence','authored_design'));

-- The companion clause of 0023's check, restated with the basis. The name is kept, so a
-- refusal still names the constraint it always named. Every comparison is written so a NULL cannot
-- make it pass: a Companion row with no stated basis is held to the evidence rule, and a missing
-- model id or prompt version fails (0023's comparisons let a NULL through).
alter table world_style_proposal drop constraint world_style_proposal_provenance_v1;
alter table world_style_proposal add constraint world_style_proposal_provenance_v1 check (
  (provenance_schema_version=0 and model_id is null and prompt_version is null
    and appearance_basis is null) or
  (provenance_schema_version=1 and
   ((origin='companion'
     and coalesce(length(btrim(model_id)), 0) > 0
     and coalesce(length(btrim(prompt_version)), 0) > 0
     and ((coalesce(appearance_basis,'evidence')='evidence' and cardinality(reference_ids) > 0) or
          (coalesce(appearance_basis,'evidence')='authored_design'
            and cardinality(reference_ids) = 0))) or
    (origin<>'companion' and model_id is null and prompt_version is null
      and appearance_basis is null)) and
   jsonb_typeof(recipe_binding)='object' and recipe_binding <> '{}' and
   jsonb_typeof(capability_mapping)='object')
);

-- A version states the basis of the Companion proposal it was applied from, and only then. The
-- first version of a world has no origin at all, and states no basis.
alter table world_style_version add constraint world_style_version_appearance_basis check (
  appearance_basis is null or
  (coalesce(origin,'')='companion' and
   ((appearance_basis='evidence' and cardinality(reference_ids) > 0) or
    (appearance_basis='authored_design' and cardinality(reference_ids) = 0)))
);

commit;
