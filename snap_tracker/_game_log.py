import enum
import logging
import pathlib
import re
from dataclasses import dataclass
from typing import (
    Any,
    Generator,
    Iterable,
)

import aiopath

CARD_STAGING_RE = re.compile(
    r'StageCard'
    r'\|CardDefId=(?P<card_def_id>\w+)'
    r'\|CardEntityId=(?P<card_eid>\d+)'
    r'\|ZoneEntityId=(?P<zone_eid>\d+)'
    r'\|Turn=(?P<turn>\d)',
)
MATCH_FOUND_RE = re.compile(
    r'OnMatchmakingMatchFound'
    r'\|GameId=(?P<game_id>[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}.[0-9a-f]{12})',
    )
GAME_RESULTS_ACKED = re.compile(
    r'RemoteGame'
    r'\|SendRequestObject'
    r'\|RequestType=CubeGame.AckGameResultRequest',
)
GAME_INITIALIZING_RE = re.compile(
    r'GameManager'
    r'\|Initialize'
    r'\|gameMode=Remote'
    r'\|leagueDefId=(?P<game_mode>\w+)'
    r'\|sceneToLoadAfterGame=Play',
)
TURN_END_RE = re.compile(r'EndTurn\|Turn=(?P<turn>[1-7])')

logger = logging.getLogger(__name__)


@dataclass
class GameLogEvent:
    class Type(enum.Enum):
        CARD_STAGED = enum.auto()
        GAME_INITIALIZING = enum.auto()
        GAME_START = enum.auto()
        GAME_END = enum.auto()
        TURN_END = enum.auto()

    type: Type
    data: dict[str, Any] | None = None


@dataclass
class GameLogFileState:
    path: pathlib.Path
    pos: int

    @classmethod
    def from_path(cls, path: pathlib.Path):
        return cls(path=path, pos=path.stat().st_size)


async def _read_log(log_state):
    async with aiopath.Path(log_state.path).open('r') as f:
        await f.seek(log_state.pos)
        lines = await f.readlines()
        new_pos = await f.tell()
        logger.debug(
            'Read %d lines (%d bytes) from %s',
            len(lines),
            new_pos - log_state.pos,
            log_state.path.name,
        )
        log_state.pos = new_pos
    return lines


def _parse_log_lines(log_lines: Iterable[str]) -> Generator[GameLogEvent, None, None]:
    for line in log_lines:
        try:
            event = _parse_line(line)
            yield event
        except LookupError:
            continue


def _parse_line(line: str) -> GameLogEvent:
    if GAME_RESULTS_ACKED.match(line):
        return GameLogEvent(GameLogEvent.Type.GAME_END)
    if m := MATCH_FOUND_RE.match(line):
        return GameLogEvent(GameLogEvent.Type.GAME_START, m.groupdict())
    if m := CARD_STAGING_RE.match(line):
        return GameLogEvent(GameLogEvent.Type.CARD_STAGED, m.groupdict())
    if m := TURN_END_RE.match(line):
        return GameLogEvent(GameLogEvent.Type.TURN_END, m.groupdict())
    if m := GAME_INITIALIZING_RE.match(line):
        return GameLogEvent(GameLogEvent.Type.GAME_INITIALIZING, m.groupdict())
    raise LookupError
