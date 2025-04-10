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
from rich.table import Table
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
    PRICE_TO_INFINITY,
    Game,
    Rarity,
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
FILESYSTEM_SYNC_INTERVAL = 5  # Seconds
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


def get_game_id(state):
    try:
        return uuid.UUID(hex=state.get('Id'))
    except TypeError:
        return None


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
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.game_state = GameStateFile.from_path(self.state_dir / 'GameState.json')

        try:
            self._client = motor.motor_asyncio.AsyncIOMotorClient(os.environ['MONGODB_URI'])
            self.db = self._client.raw
        except KeyError:
            logger.exception("No MONGODB_URI set, syncing will not work.")

    # Commands

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

    def run(self):
        try:
            asyncio.run(self._arun())
        except KeyboardInterrupt:
            console.log('Shutting down.')

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

    @ensure_collection
    async def upgrades(self):
        """
        Output the list of common cards that can be upgaded (1 CL for 25 credits and 5 boosters) followed
        by a list of cards that have enough boosters for split, prioritizes cards with the highest chance of "good"
        splits and cards that are closest to split.
        """
        credits_ = self._profile['Wallet']['_currencies']['Credits']['Credits'].get('TotalAmount', 0)
        console.print(f'Hi {self.account["Name"]}!')
        console.print(f'You have {credits_} credits_ available for upgrades.')
        console.rule()

        console.print(self._find_splits(credits_))
        console.print(self._find_commons(credits_))

    # Internals

    async def _load_profile(self):
        self._profile = (await self._read_state('Profile'))['ServerState']

    @property
    def account(self):
        try:
            return self._profile['Account']
        except TypeError:
            logger.exception("Tracker._load_profile() hasn't been awaited!")

    @ensure_collection
    async def _arun(self):
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._periodic_volume_cache_write())
            tg.create_task(self._watch())

    async def _watch(self):
        paths = (self.player_log.path, self.error_log.path, self.game_state.path)
        console.log('Watching for file changes in', paths)
        try:
            async for changes in awatch(*paths, force_polling=True):
                for change in changes:
                    await self._process_change(change)
        except asyncio.CancelledError:
            console.log("Shutting down file watcher.")
        finally:
            await asyncio.sleep(0)

    async def _read_state(self, name):
        file_name = self.state_dir / f'{name}State.json'
        return await _read_file(file_name)

    async def parse_game_state(self):
        data = await self._read_state('Game')
        return data['RemoteGame']['GameState']

    async def _periodic_volume_cache_write(self):
        drive = self.game_state.path.drive
        driveletter = drive[0]
        await write_volume_caches(FILESYSTEM_SYNC_INTERVAL, driveletter)

    @ensure_account
    async def _load_collection(self):
        coll_state = await self._read_state('Collection')
        self.collection = Collection(self.account, coll_state['ServerState'])

    def _find_splits(self, credits_, max_rows=20):
        table = []
        for n, row in enumerate(self.collection._maximize_splits(credits_), 1):
            if n > max_rows and row['upgrade'].target != Rarity.INFINITY:
                break
            table.append(row)
        try:
            return rich_table(table, title='to maximize splits')
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
        match changed_path.stem:
            case 'Player':
                new_log_lines = await _read_log(self.player_log)
                await self._handle_log(new_log_lines)
            case 'ErrorLog':
                new_log_lines = await _read_log(self.error_log)
                await self._handle_log(new_log_lines)
            case 'GameState':
                await self._handle_game_state_change()
            case _:
                console.log('Unknown file change tracked:', changed_path)

    async def _handle_game_state_change(self):
        state = await self.parse_game_state()
        for path, def_id in self.find_card_def_ids(state):
            logger.debug(f"{'.'.join(path)}: {def_id}")
        cgi = state.get('ClientGameInfo')
        if cgi is not None:
            console.log('ClientGameInfo:', cgi)
        await self._handle_player_info(state)
        if (result := state.get('ClientResultMessage')) and self.ongoing_game:
            file_name = await self.handle_game_result(result)
            await self._save_state_snapshot(state, file_name)
            self.ongoing_game = None
            return
        await self._handle_locations(state)
        turn_in_state = state.get('Turn', 0)
        game_id = get_game_id(state)
        if not self.ongoing_game:
            # Old state file, waiting for new game.
            return
        # TODO: This is dangerous, if we compared the other way round without the .id they wouldn't match.
        if self.ongoing_game.id != game_id:
            console.log(
                'Game id mismatch',
                {
                    'state': game_id,
                    'tracker': self.ongoing_game,
                },
            )
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

    async def _handle_player_info(self, state):
        try:
            players = state['Players']
            p1, p2 = players
        except (KeyError, ValueError):
            pass
        else:
            p1info = p1.get('PlayerInfo')
            p2info = p2.get('PlayerInfo')
            if p1info and p2info:
                if p1info['AccountId'] == self.account['Id'] and self.ongoing_game.player_idx != 1:
                    self.ongoing_game.player_idx = 1
                    console.log('You are player 1')
                    opponent = p2
                elif p2info['AccountId'] == self.account['Id'] and self.ongoing_game.player_idx != 2:
                    self.ongoing_game.player_idx = 2
                    console.log('You are player 2')
                    opponent = p1
                if self.ongoing_game.opponent is None:
                    self.ongoing_game.opponent = opponent
                    opp_info = opponent['PlayerInfo']
                    console.log(':crossed_swords: [red]',
                                opp_info['Name'],
                                '[reset]CL:', opp_info['CollectionScore'],
                                'ATH rank:', opp_info['HighWatermarkRank'],
                                )
                logger.debug('Player1: %s', p1)
                logger.debug('Player2: %s', p2)

    async def _handle_log(self, new_log_lines):
        state = await self.parse_game_state()
        staged_turn = 0
        game_id = get_game_id(state)
        turn_in_state = state.get('Turn', 0)
        for log_event in _parse_log_lines(new_log_lines):
            logger.debug(log_event)
            match log_event.type:
                case GameLogEvent.Type.GAME_INITIALIZING:
                    console.log(f'Matchmaking for {log_event.data["game_mode"]}')
                case GameLogEvent.Type.GAME_START:
                    game_id = uuid.UUID(hex=log_event.data['game_id'])
                    self.ongoing_game = Game(game_id)
                    console.log('Matchmaking found us a game', game_id)
                    continue
                case GameLogEvent.Type.TURN_END:
                    turn = int(log_event.data['turn'])
                    console.log('Turn', turn, 'ended.')
                    self._update_current_turn(turn + 1, game_id)
                    await self._handle_game_state_change()
                    continue
                case GameLogEvent.Type.GAME_END:
                    console.log('Game finished, waiting for state to update.')
                    break
                case GameLogEvent.Type.CARD_STAGED:
                    staged_turn = max((int(log_event.data['turn']), staged_turn))
                    console.log('PLAYER: Card', log_event.data['card_def_id'],  'staged')
                    if turn_in_state < staged_turn:
                        self._update_current_turn(staged_turn, game_id)
                case GameLogEvent.Type.CARD_RESOLVED:
                    console.log('OPPONENT: Card', log_event.data['card_def_id'],  'resolved')
                case GameLogEvent.Type.CARD_DRAW:
                    console.log('Card', log_event.data['card_def_id'], 'drawn')

    async def _save_state_snapshot(self, state, file_name: str | None = None):
        ts = datetime.datetime.now(tz=datetime.UTC)
        fn = file_name if file_name is not None else f'game_state_{ts.strftime("%Y%m%dT%H%M%S%f")}.json'
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
            logger.debug('Wrote %d bytes to %s', len(contents), out_path.name)

    async def handle_game_result(self, result):
        grai = next(ai for ai in result['GameResultAccountItems'] if ai['AccountId'] == self.account['Id'])
        is_winner = grai.get('IsWinner', False)
        is_loser = grai.get('IsLoser', False)
        if is_winner == is_loser:
            console.log('[bold][red]Error: cannot determine winner')
            return None
        cubes = grai.get('FinalCubeValue')
        cubestring = ':ice:' * cubes
        game_id = self.ongoing_game.id
        if is_winner:
            console.log(f':trophy: You won {cubestring}!')
            return f'win-{game_id!s}.json'
        console.print(f':slightly_frowning_face: You lost {cubestring}')
        return f'loss-{game_id!s}.json'

    async def _handle_locations(self, state):
        return
        turn = self.ongoing_game.current_turn
        cards_at_locations = {'p1': [], 'p2': []}
        for loc in state['Locations']:
            if p1cards := loc.get('Player1Cards'):
                cards_at_locations['p1'].append(p1cards)
            if p2cards := loc.get('Player2Cards'):
                cards_at_locations['p2'].append(p2cards)
        console.log('Cards at locations on turn', turn, cards_at_locations)

    def show_prices(self):
        table = Table(title="Upgrade prices to infinity")
        table.add_column("Rarity")
        table.add_column("Credits")
        table.add_column("Boosters")
        for price in PRICE_TO_INFINITY.values():
            table.add_row(str(price.rarity), str(price.credits), str(price.boosters))
        console.print(table)

    def find_card_def_ids(self, state):
        """
        Finds all 'CardDefId' occurrences in the given state dictionary and returns their
        hierarchies and values.

        Args:
            state (dict): The dictionary to search.

        Returns:
            list: A list of tuples, where each tuple contains the key hierarchy and the
                  corresponding value, or an empty list if 'CardDefId' is not found.
        """
        target_key = "CardDefId"
        results = []

        def _recursive_search(data, hierarchy):
            if isinstance(data, dict):
                if target_key in data:
                    results.append((tuple(hierarchy + [target_key]), data[target_key]))
                for key, value in data.items():
                    _recursive_search(value, hierarchy + [key])
            elif isinstance(data, list):
                for item in data:
                    _recursive_search(item, hierarchy)

        _recursive_search(state, [])
        return results
