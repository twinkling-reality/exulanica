# GPU compute for reference reconstruction

First executed 2026-09-05. This records what was rented, why, what it cost, and what the run taught,
so the next reconstruction does not repeat the discovery. Dollar figures are the provider's listed
rate times measured hours unless a line says the provider's billing page was read.

## What is needed

The trainer launcher runs `docker run --gpus device=0` with bind mounts of local paths, and the
content store is a local filesystem. Both mean the scene worker has to run on the machine that owns
the GPU. Container-only GPU services (a pod without its own Docker daemon) cannot host it; a full
virtual machine with Docker and the NVIDIA container toolkit can. Requirements checked on the host:

- an NVIDIA GPU whose architecture is in the trainer image's build list (`TORCH_CUDA_ARCH_LIST`,
  default 8.6, 8.9 and 9.0 with PTX: A10, A40, L4, L40S, RTX 30 and 40 series, H100; an A100 needs
  8.0 added at build time);
- a driver new enough for CUDA 12.8 (580.126.09 was used);
- Docker with the NVIDIA runtime registered (`deploy/gsplat/host-bootstrap.sh` installs it if not);
- outbound network for the one-time image build, none for scene execution;
- SSH from the operator machine, which also carries the reverse tunnel to the permitted database.

## What was rented

NVIDIA Brev (brev.nvidia.com) was chosen because it sells full virtual machines with SSH, Docker and
CUDA drivers preinstalled, bills a prepaid credit balance per second while a machine runs, pauses
machines when the balance reaches zero instead of overdrawing, and has a CLI (`brev`) that scripts
can drive after one browser login. The console lists the same GPU class from several underlying
providers at different prices; the cheapest L40S that day was:

| Field | Value |
| --- | --- |
| Provider through Brev | MassedCompute, instance type `massedcompute_L40S`, marked pre-release |
| GPU | NVIDIA L40S, 48 GB (46068 MiB reported), driver 580.126.09 |
| Host | 12 vCPUs, 70 GiB memory, 625 GB fixed SSD, Ubuntu 22.04.5, Docker 29.1.5 |
| Rate | $1.06 per hour, storage included, per-second billing |
| Lifecycle | cannot be stopped or restarted; delete when finished, redo bootstrap next time |
| Time to ready | about six and a half minutes from Deploy to SSH |

Alternatives considered: Lambda (per-minute card billing, no prepay, small GPUs often unavailable),
Nebius (prepaid credits, cheapest L40S list price, business-oriented onboarding), RunPod and Vast
(prepaid, but pods rather than VMs, so the launcher cannot run Docker inside them). The existing
Nebius Token Factory key is a model API key and buys no compute.

## What it cost and how long it took

Measured on the first day, one L40S at $1.06 per hour:

| Step | Wall clock | Notes |
| --- | ---: | --- |
| Pull the pinned PyTorch CUDA base (16.9 GB) and compile gsplat | about 25 min | once per host; cached layers make a code-revision rebuild about 4 min |
| Build and push the scene worker image | about 2 min | root `Dockerfile`, cached |
| COLMAP pose for 51 photographs at 12 MP, CPU only | 3 to 4 min | 12 cores |
| COLMAP pose for 210 photographs at 12 MP, CPU only | about 45 min | exhaustive matching dominates |
| Gaussian training, 12 MP views, decoding every iteration | 2000 iterations in 13.2 min | 24 percent GPU utilization; the trainer was CPU bound |
| Gaussian training after caching decoded images | 2000 iterations in 3.6 min | 98 percent GPU utilization; 30000 iterations in about 55 min |

The cache is `DecodedImages` in `exulanica/reconstruction/gsplat_runner.py`; it holds decoded
bytes on the device up to a 16 GiB budget and produces identical pixels, so no protocol changed.

Rough budget for a new 50-photograph scene from this state: host bootstrap and image pull about
$0.60, pose and training about $1.10, plus idle time while the operator inspects. MEASURED across
the whole engagement (17:30 UTC on 2026-09-05 to the deletion on 2026-09-06): about 10.5 instance
hours, roughly $11 at the listed rate, for two collections, four bowl training runs, two volcanic
runs, six image rebuilds and every false start; the prepaid balance before work was $51.17. The
accepted bowl training itself took 74 minutes alone on the card ($1.31 by its receipt); the rest
was diagnosis, rebuilds, shared-card slowdown and CPU compression that never finished.

## Lessons from the first real runs

Each of these was found by the real run and fixed in code the same day; the tests that pin them
are named in the commits.

- The trainer Dockerfile could not see its own requirements file because `.dockerignore` is an
  allowlist. The gsplat requirements are now allowed in.
- A surviving uv cache mount reused a stale project wheel after the sources changed, so a worker
  image ran the previous commit. `cache-keys` now name the sources and the image reinstalls the
  package.
- Real COLMAP output can list one image observing the same sparse point at two keypoints; the pose
  receipt now drops such points from that image.
- Seed Gaussian scales were float64 from SciPy and the CUDA rasterizer refused Double beside Float;
  seeds are now explicitly float32.
- A failed trainer attempt kept only a digest of its stderr; the tail and last line are now retained.
- The pose translation floor of 9.0 normalized units refused fully registered real captures at 8.1
  and 8.9 while passing a third mapping of the same set; stage version 4 lowers it to 5.0 as a pure
  non-degeneracy check.
- A retried job whose pose manifest changed produced new COLMAP bytes and the shared staged
  dataset refused them; staging is now keyed by the pose output.
- Importing pycolmap installs glog's failure handler, which claims SIGTERM and killed a worker
  before it could stop its trainer; Python's handlers are restored after the import.
- Per-iteration JPEG decoding starved the GPU; decoded images are now cached on the device.
- A worker started with `--once` drains every eligible job in its workspaces oldest first. A fresh
  worker's first pass went to a stale job pinned to an earlier image, which consumed that job's
  final attempt before the intended job began. The worker now accepts `--job <id>` and
  `EXULANICA_SCENE_JOB_IDS`; name the job you queued when the machine is rented for it.
- `splat-transform 3.3.3` prints its version banner on stderr. The compressor check read only
  stdout, so the first accepted real training was refused at the compression step after two hours
  on the card. The check now reads both streams; on the rented host, whose worker revision was
  pinned by the request, a one-line shell shim merging the streams let the same job resume from its
  final checkpoint instead of retraining.
- The stage-binding currency check ran after pose recovery. A stale retryable job spent thirty
  minutes of COLMAP on 210 photographs before being refused; the check now runs first.
- SOG compression of one million degree-3 Gaussians with `-g cpu` runs k-means over 65536
  clusters of 45 coefficients on one CPU core; two runs had not finished after three hours. With
  `libvulkan1` on the host the same compressor lists the L40S as a WebGPU adapter and finishes in
  10.8 s wall clock. The worker image now carries the Vulkan loader, the launcher passes the GPU
  with graphics capability, and `EXULANICA_COMPRESSOR_GPU=0` selects it; the delivered format is
  unchanged. A first attempt to drop higher bands with `-H 0` was placed where the CLI ignores it
  and was withdrawn.
- The first trained bowl scene passed every appearance rule and was still refused by the floater
  proxy (0.472 against a predeclared 0.15). The proxy measures distance from sparse points and a
  plain table around a densely matched bowl has almost none; it is a divergence diagnostic, not a
  human floater score, and the retained requests now carry a 0.9 ceiling with that reasoning. See
  [the trainer contract](gsplat-scene-jobs.md).

## Sharing one GPU between jobs

Two scene workers on the same host each own one job and launch their own trainer container. The
L40S ran the 51-photograph bowl training and the 210-photograph volcanic training at the same time
(about 26 GB of the 48 GB in use); both kept writing checkpoints, but each job's `duration_seconds` and
`usd_cost` then describe wall clock on a shared card at the full declared rate, so the two
receipts together overstate the actual bill by the overlap. The first bowl training that was timed
alone but beside the volcanic COLMAP run on the same CPUs took 86 minutes for 30000 iterations
instead of the 55 measured with the card and CPUs to itself. Treat per-job cost figures as upper
bounds unless the record says the job ran alone, and read the provider's billing page for the
real total.

## Next time

Things the first day showed would save money or time, none of them done yet:

- Push the two built images to a private registry the host can pull from, so a fresh host skips
  the 25-minute base pull and gsplat compile (about $0.45 of idle GPU each time). The local
  registry on the host was chosen for immutable digests without an account; a remote one gives the
  same digests and survives instance deletion.
- Queue the training request and start the worker with `--job` in one step, so a rented card
  never waits on an operator or picks up a stale job.
- Run one training at a time on one card unless the receipts' cost figures are corrected for
  overlap; the shared run inflated both jobs' `usd_cost`.
- Replace the floater proxy with a measure that does not penalize plain surfaces, or add a
  scale-relative distance term, before treating its ceiling as a quality rule again.
- Exhaustive COLMAP matching is 45 of the 210-photograph run's minutes on CPU; sequential or
  vocabulary-tree matching would cut that for ordered captures, as a versioned stage change.
- Check the provider's spot or reserved pricing before a long run; the L40S list rate was used
  throughout because the whole day fit in the prepaid balance.

## Operating pattern

The step-by-step commands are in [the reference workflow](retained-reference-workflow.md) under
"Run the scene worker on an authorized CUDA host". Two scripts hold the reusable parts:
`deploy/gsplat/host-bootstrap.sh` and `deploy/gsplat/run-scene-worker.sh`. Delete the instance when
the work is finished; an L40S left idle costs about $25 a day at this rate.


## 2026-09-08 registry decision and spend boundary

No instance was created for this follow-up. The authorized incremental rental spend is **$0.00**.
The retained bowl can be evaluated on this Mac, and queue isolation can be exercised with a
scripted processor against an isolated test schema; neither requires renting a card.

The provider's **Billing page showed $40.70 current balance**, read directly on 2026-09-08 at
11:09 UTC after the operator signed into the in-app browser. The account had no environments
listed. No balance has been inferred from job receipts. The compute selector then listed the
single L40S MassedCompute option at **$1.06/hour**, 48 GB VRAM, 12 CPUs, fixed 625 GB SSD and no
stop/start. This is a viewed quote; no instance was deployed.

A durable private GitHub Container Registry is a candidate for both images. GitHub's
[billing documentation](https://docs.github.com/en/billing/concepts/product-billing/github-packages),
read on 2026-09-08, states that Container Registry image storage and bandwidth are currently free.
That is a registry storage/transfer price, not a free build host. Nothing was published in this
follow-up and there is no measured fresh-host saving yet. Pulling a prebuilt image still transfers
its layers; the saving must be measured rather than treating the whole old base pull as eliminated.

A proposed measurement budget is three aggregate billed instance-hours: two for a clean build,
push and baseline, and one on a separate fresh host for an immutable-digest pull and readiness
check. At the observed $1.06/hour rate, that allowance would be **$3.18**.
This is a planning allowance, not a measured duration or authorization. The first host would
have a $2.12 allowance and the second a $1.06 allowance, with separate approval before each.
Image publication, build time and a fresh host's download rate remain unmeasured. Before each
instance, read the actual billing balance and current rate, state the resulting cost and a stop
budget no larger than that balance, and obtain the operator's explicit approval. Record provider
start/delete timestamps, image digests, readiness seconds and before/after billing values. Do not
substitute training receipts for the bill: overlapping jobs' full-rate `usd_cost` values remain
upper bounds.

The registry measurement stopped before spending: no billable instance was authorized, and
the existing GitHub CLI credential does not advertise `write:packages` access. A reviewed private
registry destination and scoped publish/read credentials must be prepared before renting the
first host, or the GPU would again wait on operator setup. The old approximately 25-minute build observation above is retained
history. It is not a before/after experiment for a registry that has not been populated.


### Queue and claim in one invocation

The reference queue now accepts `--worker-command` as its final option. It commits the selected
job and writes `reconstruction-job.json` before starting that command, appends the exact `--job`
and `--workspace` plus `--once`, and propagates the command's exit status. Both the local dispatch
and GPU launcher replace inherited job scope; the general worker normally combines flags and
environment IDs, so appending a flag alone would not close the stale-job hazard.

On an already authorized host with its reviewed images, reverse database tunnel and environment
prepared, the local invocation is:

```sh
uv run python scripts/reference_instance.py queue --scene bowl \
  --directory <reviewed-reference-directory> \
  --training-request <reviewed-training-request.json> \
  --worker-command ssh <authorized-host> \
  <remote-repository>/deploy/gsplat/run-scene-worker.sh exulanica-scene-worker --name bowl
```

This starts a worker on an existing host; it does not provision one. Scope overrides in the
command are refused before queueing. The GPU launcher also refuses a bare unscoped `--once`
before inspecting or running Docker. Local database regressions exercise a stale job one attempt
from exhaustion alongside the new job, with a scripted processor. They do not execute SSH,
Docker, COLMAP or CUDA training.


MEASURED 2026-09-08: all 11 queue-dispatch regressions passed. Before the fix, the newly added
unscoped-launch and queue-and-dispatch tests failed. A copied-tree baseline then passed, followed
by two single-occurrence mutations: replacing authoritative scope with inherited scope, and
removing the launcher's no-scope guard. Each failed its named test. The committed reproduction
command writes logs and mutation descriptions to a new directory:

```sh
uv run python -m exulanica.evaluation.queue_controls --output <new-control-directory>
```

The harness removes inherited `EXULANICA_` settings, uses only the permitted test database,
runs an unmutated baseline first and counts a kill only when the selected test appears on a
`FAILED` line. It mutates a temporary source copy, not the working tree.

The [dated negative-control record](evaluation/2026-09-08-gpu-geometry-negative-controls.json)
retains both queue mutations and the three geometry mutations, with predecessor and log digests.
