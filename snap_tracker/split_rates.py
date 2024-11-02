"""
1st Split
    Finish
        50% chance for Foil
        50% chance for Prism
    Flare
        No Flare
2nd & 3rd Split
    Finish
        50% chance for Foil
        50% chance for Prism
    Flare
        50% chance for Glimmer
        50% chance for Tone
4th Split
    Finish
        32.5% chance for Foil
        32.5% chance for Prism
        35% chance for Ink
    Flare
        33.3% chance for Glimmer
        33.3% chance for Tone
        33.3% chance for Stardust
5th Split
    Finish
        15% chance for Foil
        15% chance for Prism
        35% chance for Ink
        35% chance for Gold
    Flare
        33.3% chance for Glimmer
        33.3% chance for Tone
        33.3% chance for Stardust
6th Split and beyond
    Finish
        15% chance for Foil
        15% chance for Prism
        35% chance for Ink
        35% chance for Gold
    Flare
        21.6% chance for Glimmer
        21.6% chance for Tone
        21.6% chance for Stardust
        35% chance for Krackle
"""
from .types import (
    Finish,
    Flare,
    SplitRate,
)


def get_split_rate(splits):
    match splits + 1:
        case 1:
            return SplitRate(
                {
                    Finish.FOIL: 0.5,
                    Finish.PRISM: 0.5,
                },
                {},
                )
        case 2 | 3:
            return SplitRate(
                {
                    Finish.FOIL: 0.5,
                    Finish.PRISM: 0.5,
                },
                {
                    Flare.Effect.TONE: 0.5,
                    Flare.Effect.GLIMMER: 0.5,
                },
            )
        case 4:
            return SplitRate(
                {
                    Finish.FOIL: 0.325,
                    Finish.PRISM: 0.325,
                    Finish.INK: 0.35,
                },
                {
                    Flare.Effect.TONE: 1 / 3,
                    Flare.Effect.GLIMMER: 1 / 3,
                    Flare.Effect.STARDUST: 1 / 3,
                },
            )
        case 5:
            return SplitRate(
                {
                    Finish.FOIL: 0.15,
                    Finish.PRISM: 0.15,
                    Finish.INK: 0.35,
                    Finish.GOLD: 0.35,
                },
                {
                    Flare.Effect.TONE: 1 / 3,
                    Flare.Effect.GLIMMER: 1 / 3,
                    Flare.Effect.STARDUST: 1 / 3,
                },
            )
        case _:
            return SplitRate(
                {
                    Finish.FOIL: 0.15,
                    Finish.PRISM: 0.15,
                    Finish.INK: 0.35,
                    Finish.GOLD: 0.35,
                },
                {
                    Flare.Effect.TONE: 0.65 / 3,
                    Flare.Effect.GLIMMER: 0.65 / 3,
                    Flare.Effect.STARDUST: 0.65 / 3,
                    Flare.Effect.KRACKLE: 0.35,
                },
            )
