"""One COLMAP stage, in a process that exits when the stage does.

``PycolmapExecutor`` spawns this module once per stage. It exists because the thing that has to be
bounded is not a leak in any single call but the fact that a long-lived process keeps whatever
pycolmap's extractor accumulated across two hundred images, and the only bound that needs no claim
about somebody else's allocator is process exit.

The protocol is two files rather than a pipe, and that is deliberate. COLMAP logs through glog to
the process's own file descriptors 1 and 2, which this process inherits so that a run says on the
operator's terminal exactly what it said before. A pipe on stdout would have to separate COLMAP's
native chatter from the result, and getting that wrong turns a stage's report into whatever the
library happened to print.

``argv`` is ``REQUEST RESPONSE``. The request carries the COLMAP argument vector, the working
directory relative paths resolve against, and the two executor options that change what a stage
produces. The response carries the ``returncode``, ``stdout`` and ``stderr`` that
``PycolmapExecutor`` would have produced running the same stage in its own process, so the
``CommandResult`` the pose controller checkpoints is built from the same strings either way.

The response is written through a temporary name and renamed, so a reader never sees half of it. A
process that dies before writing one leaves none, and the parent reports that as a failed stage
rather than a missing file: that is the case in-process execution could not produce at all, because
there the same death took the worker with it.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 2:
        raise SystemExit(
            "usage: python -m exulanica.reconstruction.pycolmap_stage_process REQUEST RESPONSE"
        )
    request = json.loads(Path(arguments[0]).read_text(encoding="utf-8"))
    # Imported here rather than at module scope so that a malformed request is reported before
    # anything pays for loading the library.
    from exulanica.reconstruction.pycolmap_executor import run_stage_here

    returncode, out, err = run_stage_here(
        tuple(str(token) for token in request["command"]),
        Path(str(request["cwd"])),
        random_seed=int(request["random_seed"]),
        camera_model=str(request["camera_model"]),
        extraction_threads=int(request["extraction_threads"]),
    )
    destination = Path(arguments[1])
    pending = destination.with_name(destination.name + ".partial")
    pending.write_text(
        json.dumps({"returncode": returncode, "stdout": out, "stderr": err}), encoding="utf-8"
    )
    os.replace(pending, destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
