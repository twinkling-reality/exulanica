# What the magenta is: an experiment, written before it is run

**Status: not run.** These parameters are committed before anybody captures a frame, so that the
result cannot be chosen to fit. Whoever runs it should run exactly this and report what it shows,
including if it shows neither of the two things below.

## The question

Every picture of the corridor taken on 2026-09-17 and 2026-09-18 shows magenta bands along both
frontages. The magenta is the runtime's unavailable state: a surface for which the tile states no
material record dresses it. **Why it is visible from the street is not established.**

This lane published an explanation on 2026-09-18 and retracted it the same night. The retracted
claim was that a viewer sees through the buildings, because the upper glazing has nothing behind
it, the interior backings being undrawn. It was wrong twice: there is no upper glazing at all, the
glazing spanning z 556 to 3404 which is the shopfront band, and the reasoning rested on a query of
this lane's own that dropped every recessed surface, which is most of a shopfront.

## The two predictions this settles

Both were made before tessellator 16 drew the interior backings, and they are opposites:

- **The tessellator lane measured** that all 51 interior backings on tile (2, 0) sit entirely
  inside a face the facade draws as solid wall, because openings are not cut, and that drawing them
  would therefore change nothing a viewer sees.
- **This lane claimed**, in the explanation it has since retracted, that drawing them would close
  the view through the shopfronts and the magenta would go.

One capture decides it, and neither lane can argue it away afterwards.

## The parameters

| | |
| --- | --- |
| containers | the tessellator 14 bake `2adf282b940f71e714ef3d40280d6ba3fd85f7874746497928619bf8714c1771`, which does not draw the backings, and any later bake that does; tessellator 16 is `b323810ae9...` |
| pose | `pose_x_mm=320000 pose_y_mm=70300 facing_dx=0 facing_dy=-1`, the across-the-street view that shows the magenta most plainly |
| viewport | 1440 by 900, as the frames it is being compared with |
| what changes | the container, and nothing else: same pose, same viewport, same page, same texture library |
| what to record | both frames, and the panel's own "surfaces drawn as unavailable" count from each |

## How to read it

- If the magenta is **gone or reduced** on the later container, the view through the shopfronts was
  the mechanism and this lane's retracted claim was right about the cause while wrong about the
  glazing.
- If the magenta is **unchanged**, the backings were never what stood between the viewer and it,
  the tessellator lane's measurement was right, and the cause is still unknown. In that case the
  next thing to measure is what lies on the line of sight from that pose: this lane found no
  undressed surface at all in the ten metre column directly in front of it, which is why the
  question is open rather than merely unanswered.

Counting the unavailable surfaces is not sufficient on its own: the count includes surfaces nobody
can see. The frames are the evidence; the counts say whether the container changed under them.
