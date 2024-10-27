import logging

logger = logging.getLogger(__name__)


def _replace_dollars_with_underscores_in_keys(d):
    for k, v in d.copy().items():
        new_key = _get_new_key(k)
        if isinstance(v, dict):
            d.pop(k)
            d[new_key] = v
            _replace_dollars_with_underscores_in_keys(v)
        else:
            d.pop(k)
            d[new_key] = v
    return d


def find_cards(d, stack=None):
    if stack is None:
        stack = []
    for k, v in d.items():
        if 'Cards' in k:
            yield stringify_stack(stack), v
        elif isinstance(v, dict):
            logger.debug(stringify_stack(stack))
            yield from find_cards(v, [*stack, k])
        elif isinstance(v, list):
            for i, d_ in enumerate(v):
                if isinstance(d_, dict):
                    yield from find_cards(d_, [*stack, k, i])


def stringify_stack(stack):
    return f"[{']['.join(s if isinstance(s, str) else str(s) for s in stack)}]"


def _get_new_key(k):
    new_key = k.replace('$', '_')
    if new_key == "_id":
        return 'id_'
    return new_key
