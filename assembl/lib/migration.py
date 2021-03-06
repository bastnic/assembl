from __future__ import absolute_import

import sys

from pyramid.paster import get_appsettings
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory

from ..lib.sqla import configure_engine, get_metadata, get_session_maker
import transaction


def bootstrap_db(config_uri=None, with_migration=True):
    """Bring a blank database to a functional state."""

    db = get_session_maker()

    if with_migration:
        context = MigrationContext.configure(db().connection())
        db_version = context.get_current_revision()

        if db_version:
            sys.stderr.write('Database already initialized. Bailing out.\n')
            sys.exit(2)

        config = Config(config_uri)
        script_dir = ScriptDirectory.from_config(config)
        heads = script_dir.get_heads()

        if len(heads) > 1:
            sys.stderr.write('Error: migration scripts have more than one '
                             'head.\nPlease resolve the situation before '
                             'attempting to bootstrap the database.\n')
            sys.exit(2)

    import assembl.models
    get_metadata().create_all(db().connection())
    # import after session to delay loading of BaseOps
    from assembl.auth.models import (
        populate_default_permissions, populate_default_roles)
    populate_default_permissions(db())
    populate_default_roles(db())

    # Clean up the sccoped session to allow a later app instantiation.

    if with_migration and heads:
        context = MigrationContext.configure(db().connection())
        context._update_current_rev(db_version, heads[0])


def ensure_db_version(config_uri, session_maker):
    """Exit if database is not up-to-date."""
    config = Config(config_uri)
    script_dir = ScriptDirectory.from_config(config)
    heads = script_dir.get_heads()

    if len(heads) > 1:
        sys.stderr.write('Error: migration scripts have more than one head.\n'
                         'Please resolve the situation before attempting to '
                         'start the application.\n')
        sys.exit(2)
    else:
        repo_version = heads[0] if heads else None

    context = MigrationContext.configure(session_maker()().connect())
    db_version = context.get_current_revision()

    if not db_version:
        sys.stderr.write('Database not initialized.\n'
                         'Try this: "assembl-db-manage %s bootstrap".\n'
                         % config_uri)
        sys.exit(2)

    if db_version != repo_version:
        sys.stderr.write('Stopping: DB version (%s) not up-to-date (%s).\n'
                         % (db_version, repo_version))
        sys.stderr.write('Try this: "assembl-db-manage %s upgrade head".\n'
                         % config_uri)
        sys.exit(2)


def is_migration_script():
    """Determine weather the current process is a migration script."""
    return 'alembic' in sys.argv[0] or 'assembl-db-manage' in sys.argv[0]


def includeme(config):
    """Initialize Alembic-related stuff at app start-up time."""
    skip_migration = config.registry.settings.get('app.skip_migration')
    if not skip_migration and not is_migration_script():
        ensure_db_version(config.registry.settings['config_uri'], get_session_maker())
