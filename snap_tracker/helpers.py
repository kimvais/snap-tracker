import codecs
import hashlib
import json
import logging
from functools import wraps
from typing import Any

import aiofiles
import stringcase
from rich.highlighter import ReprHighlighter
from rich.protocol import is_renderable
from rich.table import Table

logger = logging.getLogger(__name__)

_hl = ReprHighlighter()


def hl(obj):
    return _hl(str(obj))


def rich_table(data: list[dict[str, Any]], title: str=None):
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
        # Await the hardcoded method from the same instance (`self`)
        await self._load_collection()
        return await func(self, *args, **kwargs)

    return wrapper


async def _read_file(fn):
    logger.debug("loading %s", fn.stem)
    async with aiofiles.open(fn, 'rb') as f:
        contents = await f.read()
        if contents[:3] == codecs.BOM_UTF8:
            data = contents[3:]
            payload = json.loads(data.decode())
        else:
            raise ValueError(contents[:10])
        return payload
