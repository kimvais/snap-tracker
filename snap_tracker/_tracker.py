import asyncio
import datetime
import hashlib
import json
import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import motor.motor_asyncio
import platformdirs
from aiopath import AsyncPath
from watchfiles import awatch

from snap_tracker._console import console
from snap_tracker._game_log import (
    GameLogEvent,
    GameLogFileState,
    _parse_log_lines,
    _read_log,
)
from snap_tracker.collection import Collection
from snap_tracker.data_types import (
    Game,
)
from snap_tracker.debug import _replace_dollars_with_underscores_in_keys
from snap_tracker.helpers import (
    _read_file,
    ensure_account,
    ensure_collection,
    rich_table,
    write_volume_caches,
)

APP_NAME = 'snap-tracker'
AUTHOR = 'kimvais'
FILESYSTEM_SYNC_INTERVAL = 2  # Seconds
GAME_DATA_DIRECTORY = r'%LOCALAPPDATA%low\Second Dinner\SNAP'
logger = logging.getLogger(__name__)


@dataclass
class GameStateFile:
    path: Path
    sha2: str

    @classmethod
    def from_path(cls, path: Path):
        with path.open('rb') as f:
            sha2 = hashlib.sha256(f.read()).hexdigest()
        return cls(path, sha2)


class Tracker:
    def __init__(self):
        console.log('Setting up the tracker')
        # Set up the game.
        self.ongoing_game: Game | None = None
        self.collection: Collection | None = None
        self._profile: dict[str, Any] | None = None

        dir_fn = os.path.expandvars(GAME_DATA_DIRECTORY)
        self.data_dir: Path = Path(dir_fn)
        self.state_dir: Path = self.data_dir / 'Standalone' / 'States' / 'nvprod'
        self.error_log = GameLogFileState.from_path(self.data_dir / 'ErrorLog.txt')
        self.player_log = GameLogFileState.from_path(self.data_dir / 'Player.log')
        self.cache_dir: Path = Path(platformdirs.user_cache_dir(APP_NAME, AUTHOR))
        self.game_state = GameStateFile.from_path(self.state_dir / 'GameState.json')

        os.makedirs(self.cache_dir, exist_ok=True)
        try:
            self._client = motor.motor_asyncio.AsyncIOMotorClient(os.environ['MONGODB_URI'])
            self.db = self._client.raw
        except KeyError:
            logger.exception("No MONGODB_URI set, syncing will not work.")

    async def _load_profile(self):
        self._profile = (await self._read_state('Profile'))['ServerState']

    @property
    def account(self):
        try:
            return self._profile['Account']
        except TypeError:
            logger.exception("Tracker._load_profile() hasn't been awaited!")

    @ensure_collection
    async def card_stats(self):
        data = []
        for i, card in enumerate(sorted(self.collection.values(), key=lambda c: c.score, reverse=True), 1):
            data.append(
                {
                    'rank': i,
                    'score': card.score,
                    'card': card.name,
                    'variants': len(card.variants),
                    'splits': card.splits,
                },
            )
        table = rich_table(data, title='your best performing cards')
        console.print(table)

    @ensure_collection
    async def _arun(self):
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._periodic_volume_cache_write())
            tg.create_task(self._watch())

    def run(self):
        try:
            asyncio.run(self._arun())
        except KeyboardInterrupt:
            console.log('Shutting down.')

    async def _watch(self):
        console.log('Watching for file changes')
        try:
            async for changes in awatch(self.player_log.path, self.error_log.path, force_polling=True):
                for change in changes:
                    await self._process_change(change)
        except asyncio.CancelledError:
            console.log("Shutting down file watcher.")
        finally:
            await asyncio.sleep(0)

    @ensure_collection
    async def sync(self):
        logging.info('Using game data directory %s', self.state_dir)
        for fn in self.state_dir.glob('*.json'):
            data = await _read_file(fn)
            query = {
                '_id': fn.stem,
            }
            update = {
                '$set': _replace_dollars_with_underscores_in_keys(data),
            }
            result = await self.db.game_files.update_one(query, update, upsert=True)
            logger.info(result)

    async def _read_state(self, name):
        file_name = self.state_dir / f'{name}State.json'
        return await _read_file(file_name)

    async def parse_game_state(self):
        data = await self._read_state('Game')
        return data['RemoteGame']['GameState']
        # _player, _opponent = game_state['Players']

    async def _periodic_volume_cache_write(self):
        drive = self.game_state.path.drive
        driveletter = drive[0]
        await write_volume_caches(FILESYSTEM_SYNC_INTERVAL, driveletter)

    @ensure_collection
    async def upgrades(self):
        credits_ = self._profile['Wallet']['_creditsCurrency'].get('TotalAmount', 0)
        console.print(f'Hi {self.account["Name"]}!')
        console.print(f'You have {credits_} credits_ available for upgrades.')
        console.rule()

        console.print(self._find_commons(credits_))
        console.print(self._find_splits(credits_))

    @ensure_account
    async def _load_collection(self):
        coll_state = await self._read_state('Collection')
        self.collection = Collection(self.account, coll_state['ServerState'])

    def _find_splits(self, credits_):
        try:
            return rich_table(self.collection._maximize_splits(credits_), title='to maximize splits')
        except ValueError:
            return '[red]No cards to upgrade for splits.'

    def _find_commons(self, credits_):
        try:
            return rich_table(self.collection._maximize_level(credits_), title='to maximize collection level')
        except ValueError:
            return '[red]No ccommon cards to upgrade.'

    def _update_current_turn(self, turn, game_id):
        if self.ongoing_game is None:
            # Tracked was started mid-game
            self.ongoing_game = Game(game_id, current_turn=(turn))
            console.log('Started tracking game', game_id, 'on turn:', turn)
        elif turn > self.ongoing_game.current_turn:
            console.log('Setting turn to', turn)
            self.ongoing_game.current_turn = turn

    async def _process_change(self, change):
        _change_type, changed_file = change
        changed_path = Path(changed_file)
        staged_turn = 0
        match changed_path.stem:
            case 'Player':
                new_log_lines = await _read_log(self.player_log)
            case 'ErrorLog':
                new_log_lines = await _read_log(self.error_log)
            case _:
                console.log('Unknown file change tracked:', changed_path)
        state = await self.parse_game_state()
        if (result := state.get('ClientResultMessage')) and self.ongoing_game:
            await self.handle_game_result(result)
            return
        turn_in_state = state.get('Turn', 0)
        try:
            game_id = uuid.UUID(hex=state.get('Id'))
        except TypeError:
            game_id = None
        # console.log(':game_die: Read game state for ', game_id, 'turn', turn_in_state)
        for log_event in _parse_log_lines(new_log_lines):
            logger.debug(log_event)
            match log_event.type:
                case GameLogEvent.Type.GAME_START:
                    game_id = uuid.UUID(hex=log_event.data['game_id'])
                    self.ongoing_game = Game(game_id)
                    console.log('Matchmaking found us a game', game_id)
                    continue
                case GameLogEvent.Type.TURN_END:
                    self._update_current_turn(int(log_event.data['turn']), game_id)
                    continue
                case GameLogEvent.Type.GAME_END:
                    console.log('Got game results, trying to find results from state.')
                    state = await self.parse_game_state()
                    if result := state.get('ClientResultMessage'):
                        await self.handle_game_result(result)
                        return
                    console.log('State has not been updated :slightly_frowning_face:')
                case GameLogEvent.Type.CARD_STAGED:
                    staged_turn = max((int(log_event.data['turn']), staged_turn))
                    if turn_in_state < staged_turn:
                        self._update_current_turn(staged_turn, game_id)

        if not self.ongoing_game:
            # Old state file, waiting for new game.
            return
        # TODO: This is dangerous, if we compared the other way round without the `.id` they wouldn't match.
        if self.ongoing_game.id != game_id:
            console.log('Game id mismatch', {'state': game_id, 'tracker': self.ongoing_game})
            return

        if not turn_in_state and self.ongoing_game is None and game_id:
            console.log('Got game_id', game_id, 'starting.')
            self.ongoing_game = Game(game_id)
        elif self.ongoing_game is not None and game_id:
            if turn_in_state < self.ongoing_game.current_turn:
                logger.debug('Stale state, not saving.')
            else:
                await self._save_state_snapshot(state)
        else:
            console.log(
                'Error: ',
                {
                    'turn_in_state': turn_in_state,
                    'game_id': game_id,
                    'ongoing_game': self.ongoing_game,
                },
                )

    async def _save_state_snapshot(self, state):
        ts = datetime.datetime.now(tz=datetime.UTC)
        fn = f'game_state_{ts.strftime("%Y%m%dT%H%M%S%f")}.json'
        out_path = AsyncPath(self.cache_dir / fn)
        contents = json.dumps(state)
        sha2 = hashlib.sha256(contents.encode('utf-8')).hexdigest()
        if sha2 == self.game_state.sha2:
            logger.debug('No change in game state.')
            return
        self.game_state.sha2 = sha2
        console.log('State updated', len(contents), 'bytes')
        async with out_path.open('w+') as f:
            await f.write(contents)
            logger.debug(f'Wrote {len(contents):d} bytes to {out_path.name}')

    async def handle_game_result(self, result):
        grai = next(ai for ai in result['GameResultAccountItems'] if ai['AccountId'] == self.account['Id'])
        is_winner = grai.get('IsWinner', False)
        is_loser = grai.get('IsLoser', False)
        assert is_winner != is_loser
        cubes = grai.get('FinalCubeValue')
        cubestring = ':ice:' * cubes
        if is_winner:
            console.log(f':trophy: You won {cubestring}!')
        else:
            console.print(f':slightly_frowning_face: You lost {cubestring}')
        self.ongoing_game = None
