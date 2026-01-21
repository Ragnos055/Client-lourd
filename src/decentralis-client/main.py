import logging
import sys
import os

# Configuration du logging - Mode DEBUG si variable d'environnement ou argument
DEBUG_MODE = os.environ.get('DECENTRALIS_DEBUG', '').lower() in ('1', 'true', 'yes') or '--debug' in sys.argv

if DEBUG_MODE:
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    print("=" * 60)
    print("  DECENTRALIS CLIENT - MODE DEBUG ACTIVÉ")
    print("=" * 60)
else:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%H:%M:%S'
    )

from gui import run_gui


def main():
    run_gui()


if __name__ == '__main__':
    main()