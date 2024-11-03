import logging
import sys

import fire

from snap_tracker._tracker import Tracker

IGNORED_STATES = {'BrazeSdkManagerState', 'TimeModelState'}


def main():
    logging.basicConfig(level=logging.ERROR)
    try:
        fire.Fire(Tracker)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == '__main__':
    main()
