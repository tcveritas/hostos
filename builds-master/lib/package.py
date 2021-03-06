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

from functools import partial
from functools import total_ordering
import fcntl
import logging
import os
import urllib2
import yaml

from lib import config
from lib import exception
from lib import package_source
from lib import repository
from lib import utils

CONF = config.get_config().CONF
LOG = logging.getLogger(__name__)


@total_ordering
class Package(object):

    __created_packages = dict()

    @classmethod
    def get_instance(cls, package_name, *args, **kwargs):
        """
        Get unique Package instance for package name, creating one on
        first call.
        """
        if package_name in cls.__created_packages.keys():
            package = cls.__created_packages[package_name]
            LOG.debug("Getting existent package instance: %s" % package)
        else:
            package = cls(package_name, *args, **kwargs)
            cls.__created_packages[package_name] = package
        return package

    def __init__(self, name):
        self.name = name
        self.clone_url = None
        self.download_source = None
        self.install_dependencies = []
        self.build_dependencies = []
        self.result_packages = []
        self.sources = []
        self.repository = None
        self.build_files = None
        self.download_build_files = []
        locks_dir = CONF.get('default').get('repositories_path')
        self.lock_file_path = os.path.join(
            locks_dir, self.name + ".lock")

        # Dependencies packages may be present in those directories in older
        # versions of package metadata. This keeps compatibility.
        OLD_DEPENDENCIES_DIRS = ["build_dependencies", "dependencies"]
        PACKAGES_DIRS = [""] + OLD_DEPENDENCIES_DIRS
        versions_repo_url = CONF.get('default').get('build_versions_repository_url')
        versions_repo_name = os.path.basename(os.path.splitext(versions_repo_url)[0])
        build_versions_repo_dir = os.path.join(
            CONF.get('default').get('build_versions_repo_dir'),
            versions_repo_name)
        for rel_packages_dir in PACKAGES_DIRS:
            packages_dir = os.path.join(
                build_versions_repo_dir, rel_packages_dir)
            package_dir = os.path.join(packages_dir, self.name)
            package_file = os.path.join(package_dir, self.name + ".yaml")
            if os.path.isfile(package_file):
                self.package_dir = package_dir
                self.package_file = package_file
                break
        else:
            raise exception.PackageDescriptorError(
                "Failed to find %s's YAML descriptor" % self.name)

        self._load()

    def __eq__(self, other):
        return self.name == other.name

    def __lt__(self, other):
        return self.name < other.name

    def __repr__(self):
        return self.name


    def download_files(self, recurse=True):
        """
        Download package source code and build files.
        Optionally, do the same for its dependencies, recursively.
        """
        # Download all package sources
        repositories_path = CONF.get('default').get('repositories_path')
        download_f = partial(package_source.download, directory=repositories_path, local_copy_subdir_name=self.name)
        self.sources = map(download_f, self.sources)

        # This is kept for backwards compatibility with older
        # 'versions' repositories.
        if self.clone_url:
            self._download_source_code()

        self._download_build_files()
        if recurse:
            for dep in (self.install_dependencies + self.build_dependencies):
                dep.download_files()

    def _download_source_code(self):
        LOG.info("%s: Downloading source code from '%s'." %
                 (self.name, self.clone_url))
        self._setup_repository(
            dest=CONF.get('default').get('repositories_path'),
            branch=CONF.get('default').get('branch'))

    def _load(self):
        """
        Read yaml file describing this package.
        """
        try:
            with open(self.package_file, 'r') as package_file:
                self.package_data = yaml.load(package_file).get('Package')
        except IOError:
            raise exception.PackageDescriptorError(
                "Failed to open %s's YAML descriptor" % self.name)

        self.name = os.path.splitext(os.path.basename(self.package_file))[0]
        self.sources = self.package_data.get('sources', [])
        for source in self.sources:
            if 'archive' not in source.values()[0]:
                source_name = source.keys()[0]
                source[source_name]['archive'] = self.name

        version = self.package_data.get('version', {})
        self.version_file_regex = (version.get('file'),
                                   version.get('regex'))

        # These are all being kept for compatibility reasons. They are
        # required in order to build old 'versions' repositories.
        #
        # This should be removed when backwards compatibility is no longer a
        # requirement. {{{
        self.clone_url = self.package_data.get('clone_url', None)
        self.download_source = self.package_data.get('download_source', None)
        self.expects_source = self.package_data.get('expects_source', self.name)
        self.branch = self.package_data.get('branch', None)
        self.commit_id = self.package_data.get('commit_id', None)
        # }}}

        LOG.info("%s: Loaded package metadata successfully" % self.name)

        # Check if this package has shared resources that need to be
        # locked from other processes
        self.locking_enabled = False
        # The URL source type is not downloaded to a shared location
        for source in self.sources:
            if "url" not in source:
                self.locking_enabled = True
                break
        if not self.sources:
            # Old sources format is used, it's better to enable locking
            self.locking_enabled = True

    def _setup_repository(self, dest=None, branch=None):
        self.repository = repository.get_git_repository(
            self.clone_url, dest)
        self.repository.checkout(self.commit_id or self.branch or branch)

    def _download_source(self, build_dir):
        """
        An alternative to just execute a given command to obtain sources.
        """
        utils.run_command(self.download_source, cwd=build_dir)
        # automatically append tar.gz if expects_source has no extension
        if self.expects_source == self.name:
            self.expects_source = "%s.tar.gz" % self.name
        return os.path.join(build_dir, self.expects_source)

    def _download_build_files(self):
        for url in self.download_build_files:
            f = urllib2.urlopen(url)
            data = f.read()
            filename = os.path.join(self.build_files, url.split('/')[-1])
            with open(filename, "wb") as file_data:
                file_data.write(data)

    def lock(self):
        """
        Locks the package to avoid concurrent operations on its shared
        resources.
        Currently, the only resource shared among scripts executed from
        different directories is the repository.
        """
        if not self.locking_enabled:
            LOG.debug("This package has no shared resources to lock")
            return

        LOG.debug("Checking for lock on file {}.".format(self.lock_file_path))
        self.lock_file = open(self.lock_file_path, "w")
        try:
            fcntl.lockf(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except IOError as exc:
            RESOURCE_UNAVAILABLE_ERROR = 11
            if exc.errno == RESOURCE_UNAVAILABLE_ERROR:
                LOG.info("Waiting for other process to finish operations "
                         "on {}.".format(self.name))
            else:
                raise
        fcntl.lockf(self.lock_file, fcntl.LOCK_EX)

    def unlock(self):
        """
        Unlocks the package to allow other processes to operate on its
        shared resources.
        """
        if not self.locking_enabled:
            return

        LOG.debug("Unlocking file {}".format(self.lock_file_path))
        fcntl.lockf(self.lock_file, fcntl.LOCK_UN)
        self.lock_file.close()
