"""A response that sends an authorized output's checked bytes as it reads them.

The preparation queue reads a prepared output and checks its hash into a file of the delivery's
own before the final read check (``WorkspacePreparationRepository.read_output``). This sends that
file a chunk at a time with its length declared, so a delivery holds one chunk in memory rather
than the whole output, and it closes the file however the response ends: sent, cut short or left
by its client. The bytes sent are the bytes checked; nothing is read from the store here.
"""

from __future__ import annotations

from collections.abc import Mapping

from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from exulanica.world.workspace_preparations import AuthorizedOutput

__all__ = ["VerifiedBodyResponse"]


class VerifiedBodyResponse(StreamingResponse):
    """An authorized output's bytes, streamed from its file, closed when the response ends."""

    def __init__(self, output: AuthorizedOutput, *, headers: Mapping[str, str]) -> None:
        self._output = output
        super().__init__(
            output.chunks(),
            media_type=output.media_type,
            headers={**headers, "Content-Length": str(output.byte_size)},
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._output.close()
