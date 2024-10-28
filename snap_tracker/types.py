import enum
import itertools
from dataclasses import (
    dataclass,
    field,
)
from enum import Enum
from functools import cached_property


def _calculate_prices():
    _total_costs = (
        (Rarity.COMMON, 0, 0),
        (Rarity.UNCOMMON, 25, 5),
        (Rarity.RARE, 125, 15),
        (Rarity.EPIC, 325, 35),
        (Rarity.LEGENDARY, 625, 65),
        (Rarity.ULTRA, 1025, 105),
        (Rarity.INFINITY, 1525, 155),
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
    credits: int
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


class Finish(enum.Enum):
    FOIL = 'foil'
    PRISM = 'prism'
    INK = 'ink'
    GOLD = 'gold'


class Flare(enum.Enum):
    GLIMMER = 'glimmer'
    TONE = 'tone'
    STARDUST = 'stardust'
    KRACKLE = 'krackle'


@dataclass
class SplitRate:
    finish: dict[Finish, float]
    flare: dict[Flare, float]
