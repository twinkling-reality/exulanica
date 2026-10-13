-- A terrain realization has no grammar seed or flat world-kind requirements.
-- Preserve the earlier receipt predicate for every other composer.
begin;
select pg_advisory_xact_lock(119622309);

alter table world_generation_receipt
  drop constraint world_generation_receipt_states_its_generation;
alter table world_generation_receipt
  add constraint world_generation_receipt_states_its_generation check (
    (case when receipt->'composer' = '{"key":"site-plan","version":3}'::jsonb
      then receipt->>'profile' = 'exulanica.generated-world/v1'
        and receipt ?& array['profile','world_id','composer','authoring','authoring_sha256',
                            'arrival','output_digest','record_count']
        and receipt - array['profile','world_id','composer','authoring','authoring_sha256',
                            'arrival','output_digest','record_count'] = '{}'::jsonb
        and jsonb_typeof(receipt->'authoring') = 'object'
        and receipt->'authoring'->>'profile' = 'exulanica.terrain-authoring/v1'
        and receipt->>'authoring_sha256' ~ '^[0-9a-f]{64}$'
        and receipt->>'output_digest' = receipt->>'authoring_sha256'
        and jsonb_typeof(receipt->'arrival') = 'object'
        and receipt->'record_count' = '1'::jsonb
      else receipt->>'profile' = 'exulanica.generated-world/v1'
        and receipt->>'seed' ~ '^[0-9a-f]{64}$'
        and receipt->>'output_digest' ~ '^[0-9a-f]{64}$'
        and case when receipt->'composer'->>'key' = 'site-plan'
          then jsonb_typeof(receipt->'kind') = 'object'
            and jsonb_typeof(receipt->'kind'->'document') = 'object'
            and receipt->'kind'->>'sha256' ~ '^[0-9a-f]{64}$'
            and jsonb_typeof(receipt->'values') = 'object'
            and not (receipt ? 'tiles')
          else jsonb_typeof(receipt->'recipe') = 'object'
            and jsonb_typeof(receipt->'specification') = 'object'
            and jsonb_typeof(receipt->'tiles') = 'array'
            and jsonb_array_length(receipt->'tiles') between 1 and 256
          end
      end) is true);

commit;
