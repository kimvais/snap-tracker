import codecs
import itertools
import json
import logging
import os
import pathlib
from collections import Counter
from dataclasses import (
    dataclass,
    field,
)
from enum import Enum
from functools import cached_property

import aiofiles
import fire
import motor.motor_asyncio
from watchfiles import awatch
from snap_tracker.debug import (
    _replace_dollars_with_underscores_in_keys,
    find_cards,
)

logger = logging.getLogger(__name__)


def _calculate_prices():
    _total_costs = (
        (Rarity.COMMON, 0, 0),
        (Rarity.UNCOMMON, 25, 5),
        (Rarity.RARE, 125, 15),
        (Rarity.EPIC, 325, 35),
        (Rarity.LEGENDARY, 625, 65),
        (Rarity.ULTRA, 1025, 105),
        (Rarity.INFINITY, 1525, 155)
    )
    Ranks = Enum('Rank', [(c[0].value, i) for i, c in enumerate(reversed(_total_costs), 1)])
    upgrades = itertools.combinations(_total_costs, 2)
    for pair in upgrades:
        lower = min(pair, key=lambda p: p[1])
        upper = max(pair, key=lambda p: p[1])
        from_ = lower[0]
        to = upper[0]
        credit_cost = upper[1] - lower[1]
        booster_cost = upper[2] - lower[2]
        yield Price(
            from_,
            to,
            credit_cost,
            booster_cost,
            Ranks[to].value,
        )


class Rarity(str, Enum):
    COMMON = 'Common'
    UNCOMMON = 'Uncommon'
    RARE = 'Rare'
    EPIC = 'Epic'
    LEGENDARY = 'Legendary'
    ULTRA = 'UltraLegendary'
    INFINITY = 'Infinity'

    def __str__(self):
        return self.name.title()

    __repr__ = __str__


@dataclass
class Price:
    rarity: Rarity
    target: Rarity
    credits:  int
    boosters: int
    _priority: int

    def __str__(self):
        return f'{self.rarity} -> {self.target} for {self.credits}/{self.boosters} = {self.collection_points}'

    __repr__ = __str__
    @property
    def is_split(self):
        return self.target == Rarity.INFINITY

    @property
    def collection_points(self):
        quotient, remainder = divmod(self.credits, 50)
        return int(quotient + remainder / 25)

PRICES = sorted(_calculate_prices(), key=lambda price: (price._priority, price.credits))


@dataclass
class Card:
    def_id: str
    boosters: int
    splits: int = 0
    variants: set = field(default_factory=set)

    @cached_property
    def different_variants(self):
        return len({v.variant_id for v in self.variants})

    def __str__(self):
        return f'<{self.def_id} ({self.splits}/{self.different_variants})>'

    @cached_property
    def number_of_common_variants(self):
        return sum(1 for v in self.variants if v.rarity == Rarity.COMMON)


@dataclass(frozen=True)
class CardVariant:
    variant_id: str
    rarity: Rarity
    is_split: bool = False
    is_favourite: bool = False


class Tracker:
    def __init__(self):
        dir_fn = os.path.expandvars(r'%LOCALAPPDATA%low\Second Dinner\SNAP\Standalone\States\nvprod')
        self.datadir = pathlib.Path(dir_fn)
        try:
            self._client = motor.motor_asyncio.AsyncIOMotorClient(os.environ['MONGODB_URI'])
            self.db = self._client.raw
        except KeyError:
            logger.error("No MONGODB_URI set, syncing will not work.")

    async def card_stats(self):
        print('Your best performing cards are:\n')
        data = await self._read_state('Profile')
        account = data['ServerState']['Account']
        counter = Counter({k: v for k,v in account['CardStats'].items() if isinstance(v, int)})
        for i, (card, points) in enumerate(counter.most_common(20), 1):
            print(f'#{i}: {card} ({points})')

    async def run(self):
        async for changes in awatch(*self.datadir.glob('*.json')):
            print(changes)

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
            print(c)

    async def upgrades(self):
        cards = await self._load_collection()
        profile_state = await self._read_state('Profile')
        profile = profile_state['ServerState']
        credits = profile['Wallet']['_creditsCurrency']['TotalAmount']
        print(f'Hi {profile["Account"]["Name"]}!\n'
              f'You have {credits} credits available for upgrades.\n'
              'This is how you should spend them:\n'
              )

        await self._maximize_collection_level(cards, credits)
        await self._maximize_splits(cards, credits)

    async def _maximize_splits(self, cards, credits):
        print("To maximize splits:")
        def _sort_fn(c):
            return c.splits, c.different_variants, c.boosters

        # Find the highest possible purchase
        possible_upgrades = []
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
                if price.credits > credits or price.boosters > card.boosters:
                    continue
                possible_upgrades.append(card)
                print(
                    f'Upgrade {card} {price} '
                    f'(you have {credits}/{card.boosters})'
                    )
                credits -= price.credits
                card.boosters -= price.boosters
        print()

    async def _load_collection(self):
        coll_state = await self._read_state('Collection')
        collection = coll_state['ServerState']
        cards = {}
        # Read card statistics
        for k, v in collection['CardDefStats']['Stats'].items():
            if not isinstance(v, dict):
                continue
            cards[k] = Card(k, splits=v.get('InfinitySplitCount', 0), boosters=v.get('Boosters', 0))
        # Read variants
        for card_dict in collection['Cards']:
            if card_dict.get('Custom', False):
                continue
            name = card_dict['CardDefId']
            variant_id = card_dict.get('ArtVariantDefId', 'Default')
            rarity = Rarity(card_dict['RarityDefId'])
            variant = CardVariant(
                variant_id,
                rarity,
                card_dict.get('Split', False),
                card_dict.get('Custom', False),
            )
            cards[name].variants.add(variant)
        return cards

    async def _maximize_collection_level(self, cards, credits):
        print("To maximize collection level:")
        potential_cards = sorted((c for c in cards.values() if c.boosters >= 5 and c.number_of_common_variants), key=lambda c: c.number_of_common_variants, reverse=True)
        collection_level = 0
        while credits and potential_cards:
            card = potential_cards.pop(0)
            upgrades = int(min((credits / 25, card.number_of_common_variants, card.boosters / 5)))
            print(f"Upgrade {upgrades} common variants of {card} for {upgrades * 25} credits and {upgrades * 5} tokens")
            credits -= upgrades * 25
            collection_level += upgrades
        print(f'...for total of {collection_level} collection level\n')


def main():
    logging.basicConfig(level=logging.ERROR)
    fire.Fire(Tracker)


if __name__ == '__main__':
    main()
