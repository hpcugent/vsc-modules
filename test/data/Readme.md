spiderT.lua
===========
* From existing spiderT.lua:

  head -2000 spiderT.lua > test/data/spiderT.lua
  echo 'herehere' >> test/data/spiderT.lua
  tail -1000 spiderT.lua >> test/data/spiderT.lua

* some manual cleanup
 * insert 2nd mpath
 * insert non-trivial default value for Bazel
 * insert default value with only the version for zsh
