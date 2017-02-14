# Copyright (C) IBM Corp. 2016.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import logging

from lib import config
from lib import distro_utils
from lib import build_manager
from lib.versions_repository import setup_versions_repository

LOG = logging.getLogger(__name__)


def run(CONF):
    setup_versions_repository(CONF)
    packages_to_build = (CONF.get('default').get('packages') or
                         config.discover_packages())
    distro = distro_utils.get_distro(
        CONF.get('default').get('distro_name'),
        CONF.get('default').get('distro_version'),
        CONF.get('default').get('arch_and_endianness'))

    LOG.info("Building packages: %s", ", ".join(packages_to_build))
    bm = build_manager.BuildManager(packages_to_build, distro)
    bm()
