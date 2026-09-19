#!/usr/bin/env python3
"""AnswerRank entry point.

    python3 run.py init          # write config
    python3 run.py tick --force  # run one full cycle
    python3 run.py run           # run the fleet 24/7
    python3 run.py dashboard     # where the business stands
"""
import sys
from answerrank.cli import main

if __name__ == "__main__":
    sys.exit(main())
