import asyncio
import codecs
import json
import logging
import pathlib
import shutil
from collections.abc import (
    Iterable,
)
from functools import wraps
from typing import (
    Any,
    Awaitable,
    Callable,
)

import aiofiles
import stringcase
from rich.highlighter import ReprHighlighter
from rich.protocol import is_renderable
from rich.table import Table

from snap_tracker._console import console

logger = logging.getLogger(__name__)

_hl = ReprHighlighter()


def hl(obj):
    return _hl(str(obj))


def rich_table(data: list[dict[str, Any]], title: str | None = None):
    if not data:
        raise ValueError
    columns = data[0].keys()
    table = Table(title=stringcase.sentencecase(title))
    for column in columns:
        table.add_column(stringcase.sentencecase(column))
    for row in data:
        table.add_row(*((v if is_renderable(v) else hl(v)) for v in row.values()))
    return table


def ensure_collection(func):
    """
    A decorator to ensure that self._load_collection() has been awaited.
    """
    @wraps(func)
    async def wrapper(self, *args, **kwargs):
        await self._load_collection()
        return await func(self, *args, **kwargs)

    return wrapper


def ensure_account(func: Callable[[Any, Any], Awaitable[Any]]) -> Callable[[Any, Any], Awaitable[Any]]:
    @wraps(func)
    async def wrapper(self, *args: Iterable[Any], **kwargs: dict[str, Any]) -> Awaitable:
        await self._load_profile()
        return await func(self, *args, **kwargs)

    return wrapper


async def _read_file(fn: pathlib.Path) -> dict[str, object]:
    logger.debug("loading %s", fn.stem)
    async with aiofiles.open(fn, 'rb') as f:
        contents = await f.read()
        if contents[:3] == codecs.BOM_UTF8:
            data = contents[3:]
            payload = json.loads(data.decode())
        else:
            raise ValueError(contents[:10])
        return payload


async def write_volume_caches(every: int = 5, driveletter: str = 'C'):
    console.log('Setting up a task to write filesystem changes to disk every', every, 'seconds on', driveletter)
    powershell = shutil.which('pwsh.exe')
    command = f'Start-Job -ScriptBlock {{Write-VolumeCache {driveletter}}}'
    process = None
    try:
        while True:
            process = await asyncio.subprocess.create_subprocess_exec(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                executable=powershell,
            )
            await process.communicate()
            logger.debug('Write-VolumeCache %s called, sleeping %d seconds', (driveletter, every))
            await asyncio.sleep(every)
    except asyncio.CancelledError:
        console.log('Shutting down periodic Write-VolumeCache.')
        try:
            process.terminate()
            await process.wait()
        except AttributeError:
            pass
    finally:
        console.log("Periodic Write-VolumeCache shut down.")
        await asyncio.sleep(0)
