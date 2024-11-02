import codecs
import json
import logging
import os
import pathlib
from collections import Counter

import aiofiles
import fire
import motor.motor_asyncio
import stringcase
from rich.console import Console
from rich.highlighter import ReprHighlighter
from rich.table import Table
from watchfiles import awatch
from snap_tracker.debug import (
    _replace_dollars_with_underscores_in_keys,
    find_cards,
)
from .types import (
    Card,
    CardVariant,
    Finish,
    Flare,
    PRICES,
    Rarity,
)

GAME_STATE_NVPROD_DIRECTORY = r'%LOCALAPPDATA%low\Second Dinner\SNAP\Standalone\States\nvprod'

logger = logging.getLogger(__name__)
console = Console(color_system="truecolor")

_hl = ReprHighlighter()


def hl(obj):
    return _hl(str(obj))


class Tracker:
    def __init__(self):
        dir_fn = os.path.expandvars(GAME_STATE_NVPROD_DIRECTORY)
        self.datadir = pathlib.Path(dir_fn)
        try:
            self._client = motor.motor_asyncio.AsyncIOMotorClient(os.environ['MONGODB_URI'])
            self.db = self._client.raw
        except KeyError:
            logger.error("No MONGODB_URI set, syncing will not work.")

    async def _get_account(self):
        data = await self._read_state('Profile')
        account = data['ServerState']['Account']
        return account

    async def _get_card_stats(self):
        account = await self._get_account()
        counter = Counter({k: v for k, v in account['CardStats'].items() if isinstance(v, int)})
        return sorted(counter.items(), key=lambda t: t[1], reverse=True)

    async def card_stats(self):
        cards = await self._load_collection()
        table = Table(title='Your best performing cards')
        table.add_column('Rank')
        table.add_column('Score')
        table.add_column('Card')
        table.add_column('Variants')
        table.add_column('Splits')
        for i, card in enumerate(sorted(cards.values(), key=lambda c: c.score, reverse=True), 1):
            table.add_row(hl(i), hl(card.score), card.name, hl(len(card.variants)), hl(card.splits))
        console.print(table)

    async def run(self):
        async for changes in awatch(*self.datadir.glob('*.json')):
            console.print(changes)

    async def sync(self):
        logging.info('Using game data directory %s', self.datadir)
        for fn in self.datadir.glob('*.json'):
            data = await self._read_file(fn)
            query = {
                '_id': fn.stem,
            }
            update = {
                '$set': _replace_dollars_with_underscores_in_keys(data),
            }
            result = await self.db.game_files.update_one(query, update, upsert=True)
            logger.info(result)

    async def _read_file(self, fn):
        logger.debug("loading %s", fn.stem)
        async with aiofiles.open(fn, 'rb') as f:
            contents = await f.read()
            if contents[:3] == codecs.BOM_UTF8:
                data = json.loads(contents[3:].decode())
            else:
                raise ValueError(contents[:10])
            return data

    async def _read_state(self, name):
        file_name = self.datadir / f'{name}State.json'
        return await self._read_file(file_name)

    async def parse_game_state(self):
        data = await self._read_state('Game')
        game_state = data['RemoteGame']['GameState']
        _player, _opponent = data['RemoteGame']['GameState']['Players']
        for stack, cards in find_cards(game_state):
            logger.info('%s: %s', stack, type(cards))
        return data

    async def test(self):
        for price in PRICES:
            logger.debug("Upgrade price: %s", price)
        collection = await self._load_collection()
        top = sorted(collection.values(), key=lambda c: (c.different_variants, c.boosters))[:10]
        for c in top:
            console.print(c)
        for ra in Rarity:
            console.print(str(ra))

    async def upgrades(self):
        cards = await self._load_collection()
        profile_state = await self._read_state('Profile')
        profile = profile_state['ServerState']
        credits = profile['Wallet']['_creditsCurrency'].get('TotalAmount', 200)
        console.print(f'Hi {profile["Account"]["Name"]}!')
        console.print(f'You have {credits} credits available for upgrades.')
        console.rule()

        console.print(await _maximize_collection_level(cards, credits))
        console.print(await _maximize_splits(cards, credits))

    async def _load_collection(self):
        coll_state = await self._read_state('Collection')
        collection = coll_state['ServerState']
        card_scores = dict(await self._get_card_stats())
        cards = {}
        # Read card statistics
        for k, v in collection['CardDefStats']['Stats'].items():
            if not isinstance(v, dict):
                continue
            score = card_scores.get(k, 0)
            cards[k] = Card(k, splits=v.get('InfinitySplitCount', 0), boosters=v.get('Boosters', 0), score=score)
        # Read variants
        for card_dict in collection['Cards']:
            if card_dict.get('Custom', False):
                continue
            name = card_dict['CardDefId']
            variant_id = card_dict.get('ArtVariantDefId', 'Default')
            rarity = Rarity(card_dict['RarityDefId'])
            if finish_def := card_dict.get('SurfaceFlare.EffectDefId'):
                finish = Finish(stringcase.snakecase(finish_def).split('_', 1)[0])
            else:
                finish = None
            flare = Flare.from_def(card_dict.get('CardRevealFlare.EffectDefId'))

            variant = CardVariant(
                variant_id,
                rarity,
                finish=finish,
                flare=flare,
                is_split=card_dict.get('Split', False),
                is_favourite=card_dict.get('Custom', False),
            )
            cards[name].variants.add(variant)
        return cards


async def _maximize_collection_level(cards, credits):
    table = Table(title="To maximize collection level")
    table.add_column("X")
    table.add_column("Card")
    table.add_column("Credits")
    table.add_column("Boosters")

    def sort_by(c):
        return (
            c.boosters,
            (c.boosters >= 5 * c.number_of_common_variants) * c.number_of_common_variants,
            c.splits,
            c.number_of_common_variants,
        )

    potential_cards = sorted(
        (c for c in cards.values() if c.boosters >= 5 and c.number_of_common_variants),
        key=sort_by,
        reverse=True
    )
    collection_level = 0
    while credits and potential_cards:
        card = potential_cards.pop(0)
        upgrades = int(min((credits / 25, card.number_of_common_variants, card.boosters / 5)))
        credit_cost = upgrades * 25
        credits -= credit_cost
        table.add_row(hl(upgrades), card.name, f'{credits} (-{credit_cost})', f'{card.boosters} (-{upgrades * 5})')
        collection_level += upgrades
    return table


async def _maximize_splits(cards, credits):
    table = Table(title='To maximize splits')
    table.add_column('Card')
    table.add_column('Upgrade')
    table.add_column('C')
    table.add_column('B')

    def _sort_fn(c):
        return c.splits, c.different_variants, c.boosters

    # Find the highest possible purchase
    possible_purchases = [p for p in PRICES if p.credits <= credits]
    for price in possible_purchases:
        logger.info("Biggest available purchase is %s", price)
        logger.info("Finding upgradable %s cards, searching for splits: %s", price.rarity, price.is_split)
        _upgrade_candidates = list(
            filter(
                lambda c: price.rarity in {v.rarity for v in c.variants},
                cards.values(),
            ),
        )
        logger.debug("You have %d %s cards", len(_upgrade_candidates), price.rarity)
        upgrade_candidates = [c for c in _upgrade_candidates if c.boosters >= price.boosters]
        logger.debug("You enough boosters to upgrade %d of those cards", len(upgrade_candidates))
        for card in sorted(upgrade_candidates, key=_sort_fn, reverse=True):
            while price.credits <= credits and price.boosters <= card.boosters:
                table.add_row(card, price, hl(credits), hl(card.boosters))
                credits -= price.credits
                card.boosters -= price.boosters
                # TODO: Update variant to new quality
    return table


def main():
    logging.basicConfig(level=logging.ERROR)
    fire.Fire(Tracker)


if __name__ == '__main__':
    main()
