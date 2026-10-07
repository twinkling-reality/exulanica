"""Give any AI agent a body in an Exulanica world, through the world's door.

A world's owner lets an agent in with a grant and hands over its key. The agent connects with
:meth:`Body.connect`, and each time one of its things may act it gets a :class:`Turn`: exactly what
one of the world's own models is shown, the actions it may take, and the function a model answers
by. It answers with one offered action, and a line when that action says something; the world
checks the answer, records it, and replays it later without the agent.

Standard library only. The MCP facade (``python -m exulanica_agent mcp``) serves the same turns as
MCP tools and needs the optional ``mcp`` package.
"""

from exulanica_agent._version import VERSION
from exulanica_agent.body import Body, HelloRefused, mapping
from exulanica_agent.happenings import Happening
from exulanica_agent.transport import AgentError, DoorRefusal
from exulanica_agent.turns import Answer, Option, Turn

__version__ = VERSION

__all__ = [
    "VERSION",
    "AgentError",
    "Answer",
    "Body",
    "DoorRefusal",
    "Happening",
    "HelloRefused",
    "Option",
    "Turn",
    "__version__",
    "mapping",
]
