# Corridor and navigation artifacts

Status: **artifact, gate, and conservative runtime adapter implemented; real gate blocked**.

`exulanica.reconstruction.navigation` builds rung-2 artifacts only from ordered metric camera poses
and independently measured navigation samples. Each sample records position, unit forward vector,
clearance radius, slope, and whether it is a source vantage or recovery pose. The build manifest
also pins the exact reconstruction and topology digests, agent radius, maximum pose gap, reviewed
lateral cap, look envelope, slope limit, and required destinations.

The lateral width at each pose is the smaller of the reviewed cap and measured clearance minus the
agent radius. It is never inferred from splat opacity or pixels. Excessive slope, insufficient
clearance, a camera gap, absent destination, missing source vantage, or missing recovery pose makes
the artifact publish rung 3 with every reason. A successful artifact binds its centreline,
per-pose widths, camera forwards, destination indices, recovery indices, and source-vantage indices
to canonical SHA-256.

The Atlas-core adapter independently checks the reconstruction and topology bases, accepted rung,
array shapes, finite values, and look bounds. It transforms the metric local centreline through the
reviewed island placement and deliberately chooses the narrowest measured width across the path.
That is conservative: it may reduce freedom compared with a segment-aware resolver and can
never expand the validated envelope. Camera look has a separate clamp around the recovered camera
forward and recorded pitch/yaw bounds.

The live scene has no persisted corridor artifact pointer because durable spatial world
authority does not exist. It therefore does not publish a rung-2 result. No real recovered
poses, collision measurements, required destinations, or topology snapshot were found locally, so
the corridor artifact gate has not passed.
