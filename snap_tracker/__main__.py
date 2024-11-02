import logging
import os
import pathlib

import fire
import motor.motor_asyncio
from rich.console import Console
from watchfiles import awatch

from snap_tracker.collection import Collection
from snap_tracker.debug import (
    _replace_dollars_with_underscores_in_keys,
    find_cards,
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

GAME_STATE_NVPROD_DIRECTORY = r'%LOCALAPPDATA%low\Second Dinner\SNAP\Standalone\States\nvprod'

logger = logging.getLogger(__name__)
console = Console(color_system="truecolor")


class Tracker:
    def __init__(self):
        dir_fn = os.path.expandvars(GAME_STATE_NVPROD_DIRECTORY)
        self.datadir = pathlib.Path(dir_fn)
        self.collection = None
        try:
            self._client = motor.motor_asyncio.AsyncIOMotorClient(os.environ['MONGODB_URI'])
            self.db = self._client.raw
        except KeyError:
            logger.error("No MONGODB_URI set, syncing will not work.")

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
        async for changes in awatch(*self.datadir.glob('*.json')):
            console.print(changes)

    @ensure_collection
    async def sync(self):
        logging.info('Using game data directory %s', self.datadir)
        for fn in self.datadir.glob('*.json'):
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
        file_name = self.datadir / f'{name}State.json'
        return await _read_file(file_name)

    async def parse_game_state(self):
        data = await self._read_state('Game')
        game_state = data['RemoteGame']['GameState']
        _player, _opponent = data['RemoteGame']['GameState']['Players']
        for stack, cards in find_cards(game_state):
            logger.info('%s: %s', stack, type(cards))
        return data

    @ensure_collection
    async def test(self):
        for price in PRICES:
            logger.debug("Upgrade price: %s", price)
        top = sorted(self.collection.values(), key=lambda c: (c.different_variants, c.boosters))[:10]
        for c in top:
            console.print(c)
        for ra in Rarity:
            console.print(str(ra))

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


def main():
    logging.basicConfig(level=logging.ERROR)
    fire.Fire(Tracker)


if __name__ == '__main__':
    main()
