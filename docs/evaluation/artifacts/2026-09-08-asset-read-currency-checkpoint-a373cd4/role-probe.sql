begin read only;
select current_database(), current_user, current_setting('transaction_isolation');
select rolname, rolsuper, rolbypassrls from pg_roles
where rolname in ('exulanica_ro','exulanica_app') order by rolname;
set local role exulanica_ro;
select current_user, current_setting('transaction_read_only');
select pg_advisory_xact_lock(hashtextextended('asset-read-checkpoint-probe',0));
select mode, granted from pg_locks where pid=pg_backend_pid() and locktype='advisory';
select n.nspname, p.proname from pg_proc p join pg_namespace n on n.oid=p.pronamespace
where p.proname in ('privacy_currency_lock','tg_training_source_mutation_lock');
rollback;
