"""Install a prepared directory without discarding the previous output on failure."""

from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import suppress
from pathlib import Path


def install_staged_directory(staging: Path, output: Path) -> None:
    """Keep a recoverable sibling backup until the new directory is installed.

    Callers validate the paths and own staging cleanup. Directory replacement is
    not an atomic exchange: readers can briefly see no output during installation.
    """
    if not output.exists():
        os.replace(staging, output)
        return

    backup = Path(tempfile.mkdtemp(prefix=f".{output.name}-backup-", dir=output.parent))
    previous = backup / "previous"
    try:
        os.replace(output, previous)
    except BaseException as backup_error:
        if previous.exists():
            raise OSError(
                f"snapshot backup move was interrupted; previous snapshot preserved at {previous}"
            ) from backup_error
        with suppress(OSError):
            backup.rmdir()
        raise

    try:
        os.replace(staging, output)
    except BaseException:
        try:
            if output.exists():
                raise FileExistsError("output appeared during failed installation")
            os.replace(previous, output)
        except BaseException as rollback_error:
            raise OSError(
                "snapshot installation and rollback failed; "
                f"previous snapshot preserved at {previous}"
            ) from rollback_error
        shutil.rmtree(backup, ignore_errors=True)
        raise

    try:
        shutil.rmtree(backup)
    except OSError as cleanup_error:
        raise OSError(
            f"new snapshot installed at {output}, but backup cleanup failed at {backup}"
        ) from cleanup_error
