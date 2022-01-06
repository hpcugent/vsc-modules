#
# Copyright 2019-2022 Ghent University
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
"""
Interaction with Lmod lua cache and JSON conversion
"""

import os
import json
import re
from atomicwrites import atomic_write
from vsc.utils.run import run, RunNoShellAsyncLoop
from distutils.version import LooseVersion
from vsc.utils.fancylogger import getLogger
from vsc.config.base import CLUSTER_DATA, MODULEROOT

LOGGER = getLogger()

LMOD_CONFIG = '/etc/lmodrc.lua'

CACHEFILENAME = 'spiderT.lua'

JSON_MODULEMAP_FILENAME = 'modulemap.json'

# this version key is the one holding the default version map
DEFAULTKEY = '.default'

MAIN_CLUSTERS_KEY = 'clusters'
MAIN_SOFTWARE_KEY = 'software'

# very dumb way to deal with difficulty to get utf8 safe data out of
# lua using print. issue might also be with run.async
SIMPLE_UTF_FIX_REGEX = re.compile(r"\\x")


class SoftwareVersion(LooseVersion):
    """Support even weirder non-sensical version schemes"""
    component_re = re.compile(r'(v?\d+ | [a-z]+ | \.)', re.VERBOSE)

    def parse(self, vstring):
        self.vstring = vstring
        components = [x for x in self.component_re.split(vstring) if x and x != '.']
        for i, obj in enumerate(components):
            try:
                # zfill and compare strings, to deal with mixed int/string versions
                #   64 should be enough for everyone etc
                #   negative versions are not properly supported anyway
                components[i] = "%064d" % int(obj.lstrip('v'))
            except ValueError:
                pass

        self.version = components

    def _cmp(self, other):
        try:
            return super(SoftwareVersion, self)._cmp(other)
        except Exception as e:
            LOGGER.error("Failed to compare %s (%s) with other %s (%s): %s",
                         self, self.version, other, other.version, e)
            raise


def run_cache_create():
    """Run the script to create the Lmod cache"""
    lmod_dir = os.environ.get("LMOD_DIR", None)
    if not lmod_dir:
        LOGGER.raiseException("Cannot find $LMOD_DIR in the environment.", RuntimeError)

    return run([os.path.join(lmod_dir, 'update_lmod_system_cache_files'), MODULEROOT])


def get_lua_via_json(filename, tablenames):
    """Dump tables from lua data in filename to json as string. Return as list"""
    if not os.path.isfile(filename):
        LOGGER.raiseException("No valid file %s found" % filename)

    tabledata = ','.join(["['%s']=%s" % (x, x) for x in tablenames])
    luatemplate = "json=require('json');dofile('%s');print(json.encode({%s}))"
    luacmd = luatemplate % (filename, tabledata)
    # default asyncloop.run is slow: if the output is very big, code reads in 1k chunks
    #   so use larger readsize
    arun = RunNoShellAsyncLoop(['lua', '-'], input=luacmd)
    arun.readsize = 1024**2
    ec, out = arun._run()
    if ec:
        LOGGER.raiseException("Lua export to json using \"%s\" failed: %s" % (luacmd, out))

    safe_out = SIMPLE_UTF_FIX_REGEX.sub("_____", out)
    data = json.loads(safe_out)

    return [data[x] for x in tablenames]


def get_lmod_conf():
    """Return Lmod config as dict"""
    # only one element, and it is a single-element list
    return get_lua_via_json(LMOD_CONFIG, ['scDescriptT'])[0][0]


def get_lmod_cache(cachefile):
    """Return Lmod lua cache as list of modulepaths and spider data"""
    return get_lua_via_json(cachefile, ['mpathMapT', 'spiderT'])


def cluster_map(mpathMapT):
    """Return cluster -> cluster module and modulepath -> [cluster1, ...] mappings"""
    # map cluster to cluster module
    clustermap = {}
    # map modulepath to list of clusters
    modulepathmap = {}
    for mpath, data in mpathMapT.items():
        for clmod in [x for x in data.keys() if x.startswith('cluster/')]:
            # also handle hidden cluster modules, incl hidden partitions
            #   (starting with . to indicate they are hidden)
            parts = clmod.split('/')[1:]
            clustername = parts[0].lstrip('.')
            if len(parts) == 2:
                partition = parts[1].lstrip('.')
                cluster = "%s/%s" % (clustername, partition)
                if clustername in clustermap:
                    LOGGER.raiseException("Found existing cluster module %s for same cluster/partition %s" %
                                          (clustername, partition))
            else:
                cluster = clustername
                partitions = [x for x in clustermap.keys() if x.startswith(clustername + "/")]
                if partitions:
                    LOGGER.raiseException("Found existing partitions %s for same cluster %s" %
                                          (partitions, clustername))

            tmpclmod = clustermap.setdefault(cluster, clmod)
            if tmpclmod != clmod:
                LOGGER.raiseException("Found 2 different cluster modules %s and %s for same cluster %s" %
                                      (tmpclmod, clmod, cluster))
            mpclusters = modulepathmap.setdefault(mpath, [])
            if cluster not in mpclusters:
                mpclusters.append(cluster)
            modulepathmap[mpath] = sorted(mpclusters)

    LOGGER.debug("Generated clustermap %s", clustermap)
    LOGGER.debug("Generated modulepathmap %s", modulepathmap)
    return clustermap, modulepathmap


def sort_modulepaths(spiderT, mpmap):
    """Return a sorted list of modulepaths"""
    modulepaths = []
    for mpath in spiderT.keys():
        if not mpath.startswith("/"):
            LOGGER.debug("Skipping spiderT key %s", mpath)
            continue

        if mpath in mpmap:
            modulepaths.append(mpath)
        else:
            LOGGER.debug("Skipping modulepath %s not in modulepath map %s", mpath, mpmap)

    modulepaths.sort()
    LOGGER.debug("Found pre-sorted modulepaths %s", modulepaths)

    # sort them
    #   very trivial sort based on EXTRA_MODULEPATHS from CLUSTER_DATA
    #   we do not assume complicated nesting
    #   just search all EXTRA_MODULEPATHS last
    #      they are listed in prepend order, but default/most sensible one is prepended last
    #      so they are reversed: the first extra has to be moved as far as possible
    for extras in [x.get('EXTRA_MODULEPATHS', [])[::-1] for x in CLUSTER_DATA.values()]:
        for extra in extras:
            # move to the end (if present)
            if extra in modulepaths:
                LOGGER.debug("Moving EXTRA_MODULEPATH %s to the end", extra)
                modulepaths.remove(extra)
                modulepaths.append(extra)

    LOGGER.debug("Sorted modulepaths %s", modulepaths)
    return modulepaths


def sort_recent_versions(versions):
    """Sort versions using LooseVersion, most recent first"""
    try:
        return sorted(versions, key=SoftwareVersion, reverse=True)
    except TypeError:
        LOGGER.error("Failed to compare versions %s", versions)
        raise


def software_map(spiderT, mpmap):
    """Create a software map with what software has which versions on which cluster"""
    modulepaths = sort_modulepaths(spiderT, mpmap)

    softmap = {}
    for mpath in modulepaths:
        LOGGER.debug("Processing modulepath %s", mpath)
        clusters = mpmap[mpath]
        for name, namedata in spiderT[mpath].items():
            soft = softmap.setdefault(name, {})
            # all versions of this software in current modulepath
            mpversions = []
            for fullname, fulldata in namedata['fileT'].items():
                version = fulldata['Version']
                # sanity check
                txt = "for modulepath %s name %s fullname %s: %s" % (mpath, name, fullname, fulldata)
                if version != fulldata['canonical']:
                    LOGGER.raiseException("Version != canonical " + txt)
                if fullname != "%s/%s" % (name, version):
                    LOGGER.raiseException("fullname != name/version " + txt)

                mpversions.append(version)
                softversion = soft.setdefault(version, [])
                soft[version] = sorted(softversion + clusters)

            # determine default
            #   the default is per clusters (actually per modulepath)
            default = None
            defaultdata = namedata['defaultT']

            if defaultdata:
                value = defaultdata['value']
                if value:
                    if value.startswith(name + "/"):
                        # default has full name, we only need the versions
                        default = value[len(name)+1:]
                    else:
                        default = value

                    if default not in soft:
                        LOGGER.raiseException("Default value %s found for %s modulepath %s but not matching entry: %s" %
                                              (default, name, mpath, defaultdata))
                else:
                    # see https://easybuild.readthedocs.io/en/latest/Wrapping_dependencies.html
                    LOGGER.debug("Default without value found for %s modulepath %s: %s", name, mpath, defaultdata)

            if not default:
                default = sort_recent_versions(mpversions)[0]

            # track the default
            #   the keys also can be used as list of all clusters that have the software
            softdefault = soft.setdefault(DEFAULTKEY, {})
            for cluster in clusters:
                tmpdefault = softdefault.setdefault(cluster, default)
                if tmpdefault != default:
                    # typically due to modulepath ordering
                    LOGGER.debug("Already found default for %s for cluster %s: found %s, new %s",
                                 name, cluster, tmpdefault, default)
    return softmap


def get_json_filename():
    """Return the filename of the JSON data"""
    config = get_lmod_conf()
    return os.path.join(config['dir'], JSON_MODULEMAP_FILENAME)


def write_json(clustermap, softmap, filename=None):
    """Write JSON with cluster and software map"""
    if filename is None:
        filename = get_json_filename()

    with atomic_write(filename, overwrite=True) as outfile:
        json.dump({
            MAIN_CLUSTERS_KEY: clustermap,
            MAIN_SOFTWARE_KEY: softmap,
        }, outfile)
        LOGGER.debug("Wrote %s", filename)

    os.chmod(filename, 0o644)


def read_json(filename=None):
    """Read JSON and return cluster and software map"""
    if filename is None:
        filename = get_json_filename()
    with open(filename) as outfile:
        data = json.load(outfile)
        LOGGER.debug("Read %s", filename)

    return data[MAIN_CLUSTERS_KEY], data[MAIN_SOFTWARE_KEY]


def software_cluster_view(softmap=None):
    """
    Return a dict with list of software versions per cluster.
    First version is the default, the remainder is sorted
    """
    if softmap is None:
        _, softmap = read_json()

    clview = {}
    for name, vdata in softmap.items():
        defaults = vdata.pop(DEFAULTKEY)

        # the keys have all clusters that have software name
        for cluster in defaults.keys():
            # create nested structure cluster -> name -> versions
            clsoft = clview.setdefault(cluster, {})
            clsoft.setdefault(name, [])

        for version, clusters in vdata.items():
            for cluster in clusters:
                clview[cluster][name].append(version)

        for cluster, default in defaults.items():
            versions = sort_recent_versions(clview[cluster][name])
            clview[cluster][name] = versions
            try:
                versions.remove(default)
            except ValueError as err:
                LOGGER.raiseException("Unable to remove default %s from versions for %s cluster %s: %s" %
                                      (default, versions, name, cluster, err))

            versions.insert(0, default)  # default first

    return clview


def convert_lmod_cache_to_json():
    """Main conversion of Lmod lua cache to cluster and software mapping in JSON"""
    cachefile = os.path.join(get_lmod_conf()['dir'], CACHEFILENAME)

    mpathMapT, spiderT = get_lmod_cache(cachefile)

    clustermap, mpmap = cluster_map(mpathMapT)
    softmap = software_map(spiderT, mpmap)
    write_json(clustermap, softmap)
