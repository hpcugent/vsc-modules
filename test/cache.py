#
# Copyright 2019-2019 Ghent University
#
# This file is part of vsc-modules,
# originally created by the HPC team of Ghent University (http://ugent.be/hpc/en),
# with support of Ghent University (http://ugent.be/hpc),
# the Flemish Supercomputer Centre (VSC) (https://www.vscentrum.be),
# the Flemish Research Foundation (FWO) (http://www.fwo.be/en)
# and the Department of Economy, Science and Innovation (EWI) (http://www.ewi-vlaanderen.be/en).
#
# https://github.com/hpcugent/vsc-modules
#
# vsc-modules is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation v2.
#
# vsc-modules is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with vsc-modules.  If not, see <http://www.gnu.org/licenses/>.
#
'''
'''
import os
import shutil
import tempfile
from vsc.install.testing import TestCase
from vsc.modules import cache
from vsc.modules.cache import (
    get_lmod_conf,
    get_json_filename, write_json, read_json,
    )

import logging
logging.basicConfig(level=logging.DEBUG)


import json

class CacheTest(TestCase):
    def setUp(self):
        """Perpare to run test"""

        super(CacheTest, self).setUp()

        self.tmpdir = tempfile.mkdtemp()
        self.topdir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        # monkeypatch
        cache.LMOD_CONFIG = os.path.join(self.topdir, 'test/data/lmodrc.lua')

    def tearDown(self):
        """Clean up after running test"""
        shutil.rmtree(self.tmpdir)

        super(CacheTest, self).tearDown()

    def test_lmod_conf(self):
        self.assertEqual(get_lmod_conf(),
                         {'timestamp': '/apps/gent/lmodcache/timestamp', 'dir': '/apps/gent/lmodcache'})

    def test_read_write_json(self):
        """Test reading and writing the json data"""
        self.assertEqual(get_json_filename(), '/apps/gent/lmodcache/modulemap.json')

        jsonfilename = os.path.join(self.tmpdir, 'some.json')
        clustermap = {'a': 'b'}
        softmap = {'g': 'h'}
        write_json(clustermap, softmap, filename=jsonfilename)
        self.assertEqual(json.loads(open(jsonfilename).read()), {'clusters': clustermap, 'software': softmap})
        self.assertEqual(read_json(filename=jsonfilename), (clustermap, softmap))
