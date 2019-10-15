#!/usr/bin/env python
# -*- coding: latin-1 -*-
"""
Setup file for some modules related tooling
"""

import vsc.install.shared_setup as shared_setup
from vsc.install.shared_setup import sdw

PACKAGE = {
    'version': '0.0.3',
    'author': [sdw],
    'maintainer': [sdw],
    'setup_requires': [
        'vsc-install >= 0.11.5',
    ],
    'install_requires': [
        'vsc-base',
        'vsc-config',
        'vsc-utils',
        'atomicwrites',
    ],
    'tests_require': [
        'mock',
    ],
}

if __name__ == '__main__':
    shared_setup.action_target(PACKAGE)
