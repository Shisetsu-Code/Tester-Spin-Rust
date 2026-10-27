#!/usr/bin/env python3
"""Observe Pragmatic's public client bootstrap without dispatching gameplay."""
import argparse
import asyncio
from pathlib import Path

import ci_bootstrap_observe as observation

observation.PROVIDERS = ('pragmatic',)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', choices=observation.PROVIDERS, default='pragmatic')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=45)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 45:
        parser.error('--seconds must be between 1 and 45')
    asyncio.run(observation.run(args))
