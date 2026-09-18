# Track A session 1, what the run itself wrote

These are the records the runner wrote on the rented machine on 2026-09-17, copied here unchanged so
the session can be checked from the repository rather than from one Mac's disk. Every record is named
by the sha256 of its own bytes, and `tests/test_generation_and_runs.py` checks that the names still
hold and that this directory holds exactly the generations the run record pins.

- `records/`: the 64 generation records of session 1, `exulanica.appearance-generation/v1`. Each names
  its models by id, revision and weights digest, its conditioning picture by digest, the recipe it
  dresses, every sampler value with the reason it was fixed, its seed, its container image, and
  `"truth": "invented"`.
- `smoke-records/`: the 2 generation records of the smoke job that gated the session.
- `results.json`, `smoke-results.json`: what each run summarised, including the verified weights.
- `gate-smoke.json`: the seven machine-checkable conditions and their readings.
- `measurements.json`, `smoke-measurements.json`: every number in the report, from
  `measure session`, which reads only these records, the outputs and the published sets.

## What no longer exists

- The image build log and the weights-fetch log. I deleted the instance before pulling them. Every
  line quoted from them in `../track-a-session-1.log.txt` was quoted while they existed and cannot be
  checked now.
- The latents. They were never retained, which is why the band in painted render a1 cannot be placed
  more precisely than the latent grid from this run's output alone.

## What is here but not in git

- The 64 raw outputs (192 MB) and the 32 look crops with their contact sheets (31 MB) stay under
  `.exulanica/appearance/`, which git ignores. They are pinned by digest in these records, so a
  future reader can check a copy they are given, but they cannot recover the pictures from the
  repository.
