import enum
import itertools
import operator
import uuid
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
    ranks = Enum('Rank', [(c[0].value, i) for i, c in enumerate(reversed(_total_costs), 1)])
    upgrades = itertools.combinations(_total_costs, 2)
    for pair in upgrades:
        lower = min(pair, key=operator.itemgetter(1))
        upper = max(pair, key=operator.itemgetter(1))
        from_ = lower[0]
        to = upper[0]
        credit_cost = upper[1] - lower[1]
        booster_cost = upper[2] - lower[2]
        yield Price(
            from_,
            to,
            credit_cost,
            booster_cost,
            ranks[to].value,
        )


class GameMode(enum.Enum):
    RANKED = 'Ranked'


@dataclass
class Game:
    id: uuid.UUID = None
    current_turn: int = 0
    mode: GameMode = GameMode.RANKED
    player_idx: int | None = None
    opponent: dict | None = None

    @classmethod
    def new(cls, game_id: str, **kwargs):
        return cls(id=uuid.UUID(hex=game_id), **kwargs)

    def __eq__(self, other):
        if isinstance(other, Game):
            return self.id == other.id
        if isinstance(other, uuid.UUID):
            return self.id == Game(other).id
        if isinstance(other, str):
            return self.id == Game(uuid.UUID(hex=other)).id
        raise NotImplementedError


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

    def __lt__(self, other):
        return self._priority > other._priority


PRICES = sorted(_calculate_prices(), key=lambda price: (price._priority, price.credits))
PRICE_TO_INFINITY = {price.rarity: price for price in PRICES if price.target == Rarity.INFINITY}


class Finish(enum.Enum):
    BANANAS = 'bananas'
    COSMIC = 'space'
    FOIL = 'foil'
    FROSTED_FLASS = 'frosted'
    GOLD = 'gold'
    INK = 'ink'
    METALLIC = 'metallic'
    PRISM = 'prism'
    PSYCHEDELIC = 'psychedelic'
    RAYS = 'rays'
    REFRACTION = 'refraction'


@dataclass(frozen=True)
class Flare:
    class Effect(enum.Enum):
        # Names are in-game English names.
        # Values are CardRevealEffectDefId's
        BANANAS = 'bananas'
        BUBBLES = 'bubbles'
        CONFETTI = 'confetti'
        COSMIC = 'space'
        GLIMMER = 'glimmer'
        TONE = 'comic'
        SNOW = 'snow'
        STARDUST = 'sparkle'
        KRACKLE = 'kirby'

    class Color(enum.Enum):
        WHITE = 'white'
        BLACK = 'black'
        BLUE = 'blue'
        GOLD = 'gold'
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
        color = cls.Color(_rem[0]) if _rem else None
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
        gold = ':yellow_circle:' if self.has_gold else ''
        ink = ':black_heart:' if self.has_ink else ''
        return f'{self.name} <{self.splits}{gold}{ink}/{self.different_variants}> ({self.score})'

    @cached_property
    def number_of_common_variants(self):
        return sum(1 for v in self.variants if v.rarity == Rarity.COMMON)

    @cached_property
    def has_ink(self):
        return any(v.finish == Finish.INK for v in self.variants)

    @cached_property
    def has_gold(self):
        return any(v.finish == Finish.GOLD for v in self.variants)


@dataclass
class SplitRate:
    finish: dict[Finish, float]
    flare: dict[Flare.Effect, float]
