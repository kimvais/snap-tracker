import codecs
import hashlib
import json
import logging
import re
from functools import wraps
from typing import Any

import aiofiles
import stringcase
from rich.highlighter import ReprHighlighter
from rich.protocol import is_renderable
from rich.table import Table

CARD_STAGING_RE = re.compile(r'StageCard\|CardDefId=(?P<card_def_if>[A-Za-z0-9]+)\|CardEntityId=(?P<card_eid>\d+)\|ZoneEntityId=(?P<zone_eid>\d+)\|Turn=(?P<turn>\d)')

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
        await self._load_collection()
        return await func(self, *args, **kwargs)

    return wrapper


def ensure_account(func):
    @wraps(func)
    async def wrapper(self, *args, **kwargs):
        await self._load_profile()
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


def _parse_log_lines(log_lines):
    for line in log_lines:
        if m := CARD_STAGING_RE.match(line):
            yield m.groupdict()
