"""Add slug to Discussion

Revision ID: 2e1a77e61fb3
Revises: 43e84f11dbaf
Create Date: 2013-08-09 19:30:21.997647

"""

# revision identifiers, used by Alembic.
revision = '2e1a77e61fb3'
down_revision = '40cee1019f16'

from alembic import context, op
import sqlalchemy as sa
import transaction

from assembl.lib import config


def upgrade(pyramid_env):
    with context.begin_transaction():
        ### commands auto generated by Alembic - please adjust! ###
        op.add_column('discussion', sa.Column('slug', sa.Unicode(), nullable=True))
        op.execute("UPDATE discussion SET slug=topic;")
        op.alter_column('discussion', 'slug', nullable=False)
        op.create_unique_constraint('slug_unique', 'discussion', ['slug'])
        ### end Alembic commands ###

    # Do stuff with the app's models here.
    with transaction.manager:
        pass


def downgrade(pyramid_env):
    with context.begin_transaction():
        ### commands auto generated by Alembic - please adjust! ###
        op.drop_column('discussion', 'slug')
        ### end Alembic commands ###
