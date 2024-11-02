import enum
import itertools
from dataclasses import (
    dataclass,
    field,
)
from enum import Enum
from functools import cached_property

import stringcase


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
        colors = {
            Rarity.COMMON: 'grey74',
            Rarity.UNCOMMON: 'chartreuse2',
            Rarity.RARE: 'steel_blue1',
            Rarity.EPIC: 'deep_pink1',
            Rarity.LEGENDARY: 'dark_orange',
            Rarity.ULTRA: 'plum1',
            Rarity.INFINITY: 'violet',
        }
        return f'[{colors[self]}]{self.name.title()}[reset]'

    __repr__ = __str__


@dataclass
class Price:
    rarity: Rarity
    target: Rarity
    credits: int
    boosters: int
    _priority: int

    def __rich__(self):
        return f'{self.rarity} -> {self.target}'

    @property
    def is_split(self):
        return self.target == Rarity.INFINITY

    @property
    def collection_points(self):
        quotient, remainder = divmod(self.credits, 50)
        return int(quotient + remainder / 25)


PRICES = sorted(_calculate_prices(), key=lambda price: (price._priority, price.credits))


class Finish(enum.Enum):
    FOIL = 'foil'
    PRISM = 'prism'
    INK = 'ink'
    GOLD = 'gold'





@dataclass(frozen=True)
class Flare:
    class Effect(enum.Enum):
        # Names are in-game English names.
        # Values are CardRevealEffectDefId's

        GLIMMER = 'glimmer'
        TONE = 'comic'
        STARDUST = 'sparkle'
        KRACKLE = 'kirby'

    class Color(enum.Enum):
        WHITE = 'white'
        BLACK = 'black'
        RED = 'red'
        PURPLE = 'purple'
        GREEN = 'green'
        RAINBOW = 'rainbow'

    effect: Effect
    color: Color = None

    @classmethod
    def from_def(cls, flare_def_id):
        if flare_def_id is None:
            return None
        flare_name, *_rem = stringcase.snakecase(flare_def_id).split('_', 1)
        color = cls.Color(next(_rem)) if _rem else None
        return cls(cls.Effect(flare_name), color)


@dataclass(frozen=True)
class CardVariant:
    variant_id: str
    rarity: Rarity
    finish: Finish = None
    flare: Flare = None
    is_split: bool = False
    is_favourite: bool = False


@dataclass
class Card:
    def_id: str
    boosters: int
    splits: int = 0
    variants: set[CardVariant] = field(default_factory=set)
    score: int = 0

    @cached_property
    def different_variants(self):
        return len({v.variant_id for v in self.variants})

    @property
    def name(self):
        return stringcase.titlecase(self.def_id)

    def __rich__(self):
        return f'{self.name} <{self.splits}/{self.different_variants}> ({self.score})'

    @cached_property
    def number_of_common_variants(self):
        return sum(1 for v in self.variants if v.rarity == Rarity.COMMON)


@dataclass
class SplitRate:
    finish: dict[Finish, float]
    flare: dict[Flare.Effect, float]
