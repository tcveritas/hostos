import logging
import os

from lib import exception
from lib import repository


LOG = logging.getLogger(__name__)


def setup_versions_repository(config):
    """
    Clone and checkout the packages metadata git repository and halt execution if
    anything fails.
    """
    path, _ = os.path.split(
        config.get('default').get('build_versions_repo_dir'))
    url = config.get('default').get('build_versions_repository_url')
    branch = config.get('default').get('build_version')
    try:
        versions_repo = repository.get_git_repository(url, path)
        versions_repo.checkout(branch)
    except exception.RepositoryError:
        LOG.error("Failed to checkout versions repository")
        raise

    return versions_repo
