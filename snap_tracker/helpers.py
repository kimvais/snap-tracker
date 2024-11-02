from typing import Any

import stringcase
from rich.highlighter import ReprHighlighter
from rich.protocol import is_renderable
from rich.table import Table

_hl = ReprHighlighter()


def hl(obj):
    return _hl(str(obj))


def rich_table(data: list[dict[str, Any]], title: str=None):
    if not data:
        return f'No cards available for upgrade {title}.'
    columns = data[0].keys()
    table = Table(title=stringcase.sentencecase(title))
    for column in columns:
        table.add_column(stringcase.sentencecase(column))
    for row in data:
        table.add_row(*((v if is_renderable(v) else hl(v)) for v in row.values()))
    return table

