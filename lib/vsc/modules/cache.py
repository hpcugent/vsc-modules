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
"""
Interaction with Lmod lua cache and JSON conversion
"""

import os
import json
from vsc.utils.run import RunNoShellAsyncLoop
from distutils.version import LooseVersion
from vsc.utils.fancylogger import setLogLevelDebug, getLogger
from vsc.config.base import CLUSTER_DATA

LOGGER = getLogger()

LMOD_CONFIG = '/etc/lmodrc.lua'

CACHEFILENAME = 'spiderT.lua'

JSON_MODULEMAP_FILENAME = 'modulemap.json'

# this version key is the one holding the default version map
DEFAULTKEY = '.default'

MAIN_CLUSTERS_KEY = 'clusters'
MAIN_SOFTWARE_KEY = 'software'


def get_lua_via_json(filename, tablenames):
    """Dump tables from lua data in filename to json as string. Return as list"""
    if not os.path.isfile(filename):
        LOGGER.raiseException("No valid file %s found" % filename)

    tabledata = ','.join(["['%s']=%s" % (x, x) for x in tablenames])
    luacmd = "json=require('json');dofile('%s');print(json.encode({%s}))"
    # default asyncloop.run is slow: if the output is very big, code reads in 1k chunks
    #   so use larger readsize
    run = RunNoShellAsyncLoop(['lua', '-'], input=(luacmd % (filename, tabledata)))
    run.readsize = 1024**2
    _, out = run._run()
    data = json.loads(out)

    return [data[x] for x in tablenames]


def get_lmod_conf():
    """Return Lmod config as dict"""
    # only one element, and it is a single-element list
    return get_lua_via_json(LMOD_CONFIG, ['scDescriptT'])[0][0]


def get_lmod_cache(cachefile):
    """Return Lmod lua cache as list of modulepaths and spider data"""
    return get_lua_via_json(cachefile, ['mpathMapT', 'spiderT'])


def cluster_maps(mpathMapT):
    """Return cluster -> cluster module and modulepath -> [cluster1, ...] mappings"""
    # map cluster to cluster module
    clustermap = {}
    # map modulepath to list of clusters
    modulepathmap = {}
    for mpath, data in mpathMapT.items():
        for clmod in data.keys():
            if not clmod.startswith('cluster/'):
                continue
            cluster = clmod.split('/')[1].lstrip('.')
            tmpclmod = clustermap.setdefault(cluster, clmod)
            if tmpclmod != clmod:
                LOGGER.raiseException("Found 2 different cluster modules %s and %s for same cluster %s" %
                                      (tmpclmod, clmod, cluster))
            mpclusters = modulepathmap.setdefault(mpath, [])
            if cluster not in mpclusters:
                mpclusters.append(cluster)

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
            # move to the end
            LOGGER.debug("Moving EXTRA_MODULEPATH %s to the end", extra)
            try:
                modulepaths.remove(extra)
            except ValueError as e:
                LOGGER.error("Did not find EXTRA_MODULEPATH %s in modulespaths %s: %s", extra, modulepaths, e)

            modulepaths.append(extra)

    LOGGER.debug("Sorted modulepaths %s", modulepaths)
    return modulepaths


def sort_recent_versions(versions):
    """Sort versions using LooseVersion, most recent first"""
    looseversions = map(LooseVersion, versions)
    return [x.vstring for x in sorted(looseversions)][::-1]


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
                    LOGGER.raiseException("Version!=canocincal "+txt)
                if fullname != "%s/%s" % (name, version):
                    LOGGER.raiseException("fullname!=name/version "+txt)

                mpversions.append(version)
                softversion = soft.setdefault(version, [])
                softversion.extend(clusters)

            # determine default
            #   the default is per clusters (or per modulepath)
            default = None
            defaultdata = namedata['defaultT']

            if defaultdata:
                value = defaultdata['value']
                if value:
                    default = value

                    # default typically has full name
                    pref = name + '/'
                    if default.startswith(pref):
                        default = default[len(pref):]

                    if default not in soft:
                        LOGGER.raiseException("Default value %s found for %s modulepath %s but not matching entry: %s" %
                                              (default, name, mpath, defaultdata))
                else:
                    # see https://easybuild.readthedocs.io/en/latest/Wrapping_dependencies.html
                    LOGGER.debug("Default without vaule found for %s modulepath %s: %s" %
                                 (name, mpath, defaultdata))

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

    # TODO: make atomic
    with open(filename, 'w') as outfile:
        json.dump({
            MAIN_CLUSTERS_KEY: clustermap,
            MAIN_SOFTWARE_KEY: softmap,
        }, outfile)
        LOGGER.debug("Wrote %s", filename)


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
            except ValueError as e:
                LOGGER.raiseException("Unable to remove default %s from versions for %s cluster %s: %s" %
                                      (default, versions, name, cluster, e))

            versions.insert(0, default)  # default first

    return clview


def convert_lmod_cache_to_json():
    """Main conversion of Lmod lua cache to cluster and software mapping in JSON"""
    # you really don't want this in debug
    cachefile = os.path.join(get_lmod_conf()['dir'], CACHEFILENAME)
    mpathMapT, spiderT = get_lmod_cache(cachefile)

    setLogLevelDebug()
    clustermap, mpmap = cluster_maps(mpathMapT)
    softmap = software_map(spiderT, mpmap)
    write_json(clustermap, softmap)

if __name__ == '__main__':
    convert_lmod_cache_to_json()
    import pprint
    pprint.pprint(software_cluster_view())
