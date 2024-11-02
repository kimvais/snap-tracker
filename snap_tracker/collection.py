import logging
from collections import Counter

import stringcase

from snap_tracker.helpers import rich_table
from snap_tracker.types import (
    Card,
    CardVariant,
    Finish,
    Flare,
    PRICES,
    Rarity,
)

logger = logging.getLogger(__name__)

class Collection(dict):
    def __init__(self, account, server_state):
        super().__init__()
        self._account = account
        card_scores = dict(self._get_card_stats())
        for k, v in server_state['CardDefStats']['Stats'].items():
            if not isinstance(v, dict):
                continue
            score = card_scores.get(k, 0)
            self[k] = Card(k, splits=v.get('InfinitySplitCount', 0), boosters=v.get('Boosters', 0), score=score)
        # Read variants
        for card_dict in server_state['Cards']:
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
            self[name].variants.add(variant)

    def _get_card_stats(self):
        counter = Counter({k: v for k, v in self._account['CardStats'].items() if isinstance(v, int)})
        return sorted(counter.items(), key=lambda t: t[1], reverse=True)

    def _maximize_level(self, credits_):
        def sort_by(c):
            return (
                c.boosters,
                (c.boosters >= 5 * c.number_of_common_variants) * c.number_of_common_variants,
                c.splits,
                c.number_of_common_variants,
            )

        potential_cards = sorted(
            (c for c in self.values() if c.boosters >= 5 and c.number_of_common_variants),
            key=sort_by,
            reverse=True
        )
        collection_level = 0
        upgrades = []
        while credits_ and potential_cards:
            card = potential_cards.pop(0)
            n = int(min((credits_ / 25, card.number_of_common_variants, card.boosters / 5)))
            credit_cost = upgrades * 25
            credits_ -= credit_cost
            upgrades.append({
                'x': n,
                'card': card.name,
                'credits_': f'{credits_} (-{credit_cost})',
                'boosters': f'{card.boosters} (-{upgrades * 5})'
            })
            collection_level += upgrades
        return upgrades


    def _maximize_splits(self, credits_):
        def _sort_fn(c):
            return c.splits, c.different_variants, c.boosters

        upgrades = []
        # Find the highest possible purchase
        possible_purchases = [p for p in PRICES if p.credits <= credits_]
        for price in possible_purchases:
            logger.info("Biggest available purchase is %s", price)
            logger.info("Finding upgradable %s cards, searching for splits: %s", price.rarity, price.is_split)
            _upgrade_candidates = list(
                filter(
                    lambda c: price.rarity in {v.rarity for v in c.variants},
                    self.values(),
                ),
            )
            logger.debug("You have %d %s cards", len(_upgrade_candidates), price.rarity)
            upgrade_candidates = [c for c in _upgrade_candidates if c.boosters >= price.boosters]
            logger.debug("You enough boosters to upgrade %d of those cards", len(upgrade_candidates))
            for card in sorted(upgrade_candidates, key=_sort_fn, reverse=True):
                while price.credits <= credits_ and price.boosters <= card.boosters:
                    upgrades.append({
                        'card': card,
                        'upgrade': price,
                        'c': credits_,
                        'B': card.boosters,
                    })
                    credits_ -= price.credits
                    card.boosters -= price.boosters
                    # TODO: Update variant to new quality
        return upgrades

