-- A queued creature draft may name its requester's web reference notes.
-- Only the reference identity and bounded use record persist here, never note text.
-- The ID is not a foreign key: an unknown or foreign request has the same not-used answer.
-- Existing rows and no-reference drafts have both columns null. No privilege changes.
begin;
select pg_advisory_xact_lock(119622309);

alter table creature_draft
  add column reference_id uuid,
  add column reference_usage jsonb,
  add constraint creature_draft_reference_usage check (
    reference_usage is null or (
      reference_id is not null
      and jsonb_typeof(reference_usage) = 'object'
      and reference_usage ?& array['state','code','bundle_sha256','notes','basis']
      and reference_usage - array['state','code','bundle_sha256','notes','basis'] = '{}'::jsonb
      and (
        (
          reference_usage->>'state' in ('used','unknown')
          and jsonb_typeof(reference_usage->'bundle_sha256') = 'string'
          and reference_usage->>'bundle_sha256' ~ '^[0-9a-f]{64}$'
          and jsonb_typeof(reference_usage->'notes') = 'number'
          and reference_usage->>'notes' ~ '^([1-9]|1[0-9]|2[0-4])$'
          and reference_usage->'basis' = '["web_description"]'::jsonb
          and (
            (reference_usage->>'state' = 'used' and reference_usage->'code' = 'null'::jsonb)
            or (reference_usage->>'state' = 'unknown'
                and reference_usage->>'code' = 'reference_delivery_unknown')
          )
        )
        or (
          reference_usage->>'state' = 'not_used'
          and reference_usage->>'code' in (
            'reference_unknown', 'reference_not_finished', 'reference_purpose_differs',
            'reference_has_no_notes', 'reference_withdrawn', 'reference_not_sent')
          and reference_usage->'bundle_sha256' = 'null'::jsonb
          and reference_usage->'notes' = '0'::jsonb
          and reference_usage->'basis' = '[]'::jsonb
        )
      )
    ) is true
  );

comment on column creature_draft.reference_usage is
  'Whether web notes conditioned a replied or cached model request (used), were not sent '
  '(not_used), or may have reached a provider without a response (unknown). '
  'No claim that notes caused a particular output field.';

commit;
