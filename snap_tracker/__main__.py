import datetime
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import fire
import motor.motor_asyncio
import platformdirs
from aiopath import AsyncPath
from rich.console import Console
from watchfiles import (
    awatch,
)

from snap_tracker.collection import Collection
from snap_tracker.debug import (
    _replace_dollars_with_underscores_in_keys,
)
from snap_tracker.types import Game
from .helpers import (
    _parse_log_lines,
    _read_file,
    ensure_account,
    ensure_collection,
    rich_table,
)

APP_NAME = 'snap-tracker'
AUTHOR = 'kimvais'
GAME_DATA_DIRECTORY = r'%LOCALAPPDATA%low\Second Dinner\SNAP'
IGNORED_STATES = {'BrazeSdkManagerState', 'TimeModelState'}

logger = logging.getLogger(__name__)
console = Console(color_system="truecolor")


class Tracker:
    def __init__(self):
        # Set up the game.
        self.ongoing_game: Game | None = None
        self.collection: Collection | None = None
        self._profile: dict[str, Any] | None = None

        dir_fn = os.path.expandvars(GAME_DATA_DIRECTORY)
        self.data_dir: Path = Path(dir_fn)
        self.state_dir: Path = self.data_dir / 'Standalone' / 'States' / 'nvprod'
        self.player_log_path: Path = self.data_dir / 'Player.log'
        self.player_log_at: int = self.player_log_path.stat().st_size
        self.cache_dir: Path = Path(platformdirs.user_cache_dir(APP_NAME, AUTHOR))
        self.game_state_path: Path = self.state_dir / 'GameState.json'

        os.makedirs(self.cache_dir, exist_ok=True)
        try:
            self._client = motor.motor_asyncio.AsyncIOMotorClient(os.environ['MONGODB_URI'])
            self.db = self._client.raw
        except KeyError:
            logger.error("No MONGODB_URI set, syncing will not work.")

    async def _load_profile(self):
        self._profile = (await self._read_state('Profile'))['ServerState']

    @property
    def account(self):
        return self._profile['Account']

    @ensure_collection
    async def card_stats(self):
        data = []
        for i, card in enumerate(sorted(self.collection.values(), key=lambda c: c.score, reverse=True), 1):
            data.append({
                'rank': i,
                'score': card.score,
                'card': card.name,
                'variants': len(card.variants),
                'splits': card.splits,
            })
        table = rich_table(data, title='your best performing cards')
        console.print(table)

    @ensure_collection
    async def run(self):
        async for _ in awatch(self.player_log_path, force_polling=True):
            await self._process_changes()

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
        game_state = data['RemoteGame']['GameState']
        # _player, _opponent = game_state['Players']
        return game_state

    @ensure_collection
    async def test(self):
        state, _ = await self.parse_game_state()
        console.log(state['Players'][0]['$id'])
        console.log(state['Players'][1]['$ref'])
        winner = state.get('Winner')
        console.log(winner['$ref'])

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

    async def _process_changes(self):
        staged_turn = 0
        new_log_lines = await self._read_player_log()
        try:
            for card_staging in _parse_log_lines(new_log_lines):
                # console.log(card_staging)
                staged_turn = max((int(card_staging['turn']), staged_turn))
                self.ongoing_game.current_turn = staged_turn
        except StopIteration:
            console.log('New game!')
            self.ongoing_game = Game()
        state = await self.parse_game_state()
        turn = state.get('Turn', 0)
        game_id = state.get('Id')
        console.log(':game_die: Read game state for ', game_id, 'turn', turn)

        if not turn and game_id:
            console.log('New game', game_id, 'begun!')
            self.ongoing_game = Game.new(game_id)
        elif self.ongoing_game is not None and game_id:
            if game_id != self.ongoing_game:
                console.log('Mismatch', game_id, self.ongoing_game.id)
            try:
                game_current_turn = self.ongoing_game.current_turn
            except AttributeError:
                game_current_turn = 0
            if result := state.get('ClientResultMessage'):
                await self.handle_game_result(result)
            elif staged_turn > game_current_turn:
                 console.log('Stale state, not saving.')
            else:
                await self._save_state_snapshot(state)
            self.ongoing_game.current_turn = current_turn
            current_turn = max((game_current_turn, turn, staged_turn))
            console.log('Setting turn to', current_turn)
        else:
            console.log("Waiting for game to start.", self.ongoing_game, game_id)


    async def _read_player_log(self):
        with self.player_log_path.open() as f:
            f.seek(self.player_log_at)
            lines = f.readlines()
            new_pos = f.tell()
            console.log(f'Read {new_pos - self.player_log_at:d} bytes, {len(lines)} lines of Player.log')
            self.player_log_at = new_pos
        return lines

    async def _save_state_snapshot(self, state):
        ts = datetime.datetime.now(tz=datetime.UTC)
        fn = f'game_state_{ts.strftime("%Y%m%dT%H%M%S%f")}.json'
        out_path = AsyncPath(self.cache_dir / fn)
        async with out_path.open('w+') as f:
            contents = json.dumps(state)
            await f.write(contents)
            console.log(f'Wrote {len(contents):d} bytes to {out_path.name}')

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


def main():
    logging.basicConfig(level=logging.ERROR)
    try:
        fire.Fire(Tracker)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == '__main__':
    main()
