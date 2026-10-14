"""How far a person stands from a thing to use it, and how far a thing's places may stand from it.

Plain figures with nothing to import, so the society engines, the society grounds and the world
object catalog read them without reaching the composition of authored objects, which reads the
asset store. :mod:`exulanica.world.society_composition` applies them and names them too.
"""

from __future__ import annotations

from typing import Final

#: How far from an object's centre an inhabitant may stand and still use it: an arm's length
#: plus a step, the same for all three reviewed markers because none of them is larger than the
#: step. For a kind that states its places, it is how far a place may be from the lattice node it
#: is joined to. It is a reviewed figure rather than a fixed one, so a host may state its own
#: within the bounds the registry validation already enforces.
REVIEWED_REACH_MM = 1_500
#: The farthest reach a registry row may state, in millimetres, and so the farthest a stated place
#: may stand from its object's centre on either axis: a person using a thing stands within reach
#: of it. The world object catalog refuses a kind whose places would stand farther.
MAX_REACH_MM: Final = 10_000
#: What turning an object can take from the gap between two of its places, as a whole millimetre.
#: ``turned_point`` moves each coordinate of a place outward, away from the object's centre, by
#: less than a millimetre. Along an axis where two places lie on one side of the centre both move
#: the same way, so their gap changes by less than a millimetre; where they lie on either side,
#: they move apart. Their distance therefore shrinks by less than the square root of two, and two
#: millimetres is the least whole millimetre above it. A kind whose places stand a standing spacing
#: and this margin apart keeps every one at any yaw at its own size, and larger, since scaling up
#: only moves them apart; smaller, they come together and a row may hold fewer.
TURNED_PLACE_MARGIN_MM: Final = 2
