#!/usr/bin/env python
# -*- coding: latin-1 -*-
"""
Setup file for some modules related tooling
"""
import sys

import vsc.install.shared_setup as shared_setup
from vsc.install.shared_setup import sdw

if sys.version_info > (3, 0):
    mock = 'mock'
else:
    # mock 4.x is no longer compatible with Python 2
    mock = 'mock < 4.0'

PACKAGE = {
    'version': '0.1.2',
    'author': [sdw],
    'maintainer': [sdw],
    'setup_requires': [
        'vsc-install >= 0.15.3',
    ],
    'install_requires': [
        'vsc-base >= 3.1.1',  # fix for stdin.write in Python 3
        'vsc-config',
        'vsc-utils',
        'atomicwrites',
    ],
    'tests_require': [
        mock,
    ],
}

if __name__ == '__main__':
    shared_setup.action_target(PACKAGE)
