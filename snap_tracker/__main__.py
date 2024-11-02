import datetime
import hashlib
import json
import logging
import os
import pathlib
import sys

import fire
import motor.motor_asyncio
import platformdirs
from aiopath import AsyncPath
from rich.console import Console
from watchfiles import (
    Change,
    awatch,
)

from snap_tracker.collection import Collection
from snap_tracker.debug import (
    _replace_dollars_with_underscores_in_keys,
)
from .helpers import (
    _read_file,
    ensure_collection,
    rich_table,
)
from .types import (
    PRICES,
    Rarity,
)

APP_NAME = 'snap-tracker'
AUTHOR = 'kimvais'
GAME_DATA_DIRECTORY = r'%LOCALAPPDATA%low\Second Dinner\SNAP'
IGNORED_STATES = {'BrazeSdkManagerState', 'TimeModelState'}

logger = logging.getLogger(__name__)
console = Console(color_system="truecolor")


class Tracker:
    def __init__(self):
        dir_fn = os.path.expandvars(GAME_DATA_DIRECTORY)
        self.data_dir = pathlib.Path(dir_fn)
        self.state_dir = self.data_dir / 'Standalone' / 'States' / 'nvprod'
        self.player_log_path = self.data_dir / 'Player.log'
        self.player_log_at = self.player_log_path.stat().st_size
        self.cache_dir = pathlib.Path(platformdirs.user_cache_dir(APP_NAME, AUTHOR))
        os.makedirs(self.cache_dir, exist_ok=True)
        self.game_state_path = self.state_dir / 'GameState.json'

        try:
            self._client = motor.motor_asyncio.AsyncIOMotorClient(os.environ['MONGODB_URI'])
            self.db = self._client.raw
        except KeyError:
            logger.error("No MONGODB_URI set, syncing will not work.")

        # Set up the game.
        self.ongoing_game_id = None
        self.collection = None

    async def _get_account(self):
        data = await self._read_state('Profile')
        account = data['ServerState']['Account']
        return account

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
            await self.log_change()

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
        profile_state = await self._read_state('Profile')
        profile = profile_state['ServerState']
        credits_ = profile['Wallet']['_creditsCurrency'].get('TotalAmount', 0)
        console.print(f'Hi {profile["Account"]["Name"]}!')
        console.print(f'You have {credits_} credits_ available for upgrades.')
        console.rule()

        console.print(self._find_commons(credits_))
        console.print(self._find_splits(credits_))

    async def _load_collection(self):
        account = await self._get_account()
        coll_state = await self._read_state('Collection')
        self.collection = Collection(account, coll_state['ServerState'])

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

    async def log_change(self):
        ts = datetime.datetime.now(tz=datetime.UTC)
        state = await self.parse_game_state()
        turn = state.get('Turn', 0)
        game_id = state.get('Id')
        console.log(':game_die: Read game state for ', game_id, 'turn', turn)

        if turn == 0 and self.ongoing_game_id != game_id:
            console.log('New game', game_id, 'begun!')
            self.ongoing_game_id = game_id

        fn = f'game_state_{ts.strftime("%Y%m%dT%H%M%S%f")}.json'
        out_path = AsyncPath(self.cache_dir / fn)
        async with out_path.open('w+') as f:
            contents = json.dumps(state)
            await f.write(contents)
            console.log('Wrote %d bytes to %s', len(contents), out_path.name)

        winner = state.get('Winner')
        loser = state.get('Loser')
        total_turns = state.get('TotalTurns')
        if winner and loser and turn == total_turns:
            console.log(winner)
            await self.handle_game_result(state, winner)

    async def handle_game_result(self, state, winner):
        player_id = state['Players'][0]['$id']
        opponent_id = state['Players'][1]['$ref']
        winner_id = winner['$ref']
        cubes = state['CubeValue']
        cubestring = ':ice:' * cubes
        if player_id == winner_id:
            console.log(f':trophy: You won {cubestring}!')
        elif opponent_id == winner_id:
            console.print(f':slightly_frowning_face: You lost {cubestring}')
        self.ongoing_game_id = None


def main():
    logging.basicConfig(level=logging.ERROR)
    try:
        fire.Fire(Tracker)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == '__main__':
    main()
