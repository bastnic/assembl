"""Adding View, Expand and Collapse actions.

Revision ID: 26449b2a017b
Revises: 22290edc94b7
Create Date: 2013-08-14 15:25:43.238518

"""

# revision identifiers, used by Alembic.
revision = '26449b2a017b'
down_revision = '22290edc94b7'

from alembic import context, op
import sqlalchemy as sa
import transaction

from assembl.lib import config


def upgrade(pyramid_env):
    with context.begin_transaction():
        ### commands auto generated by Alembic - please adjust! ###
        op.create_table('collapse',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['id'], ['action.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_table('expand',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['id'], ['action.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.create_table('view',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['id'], ['action.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
        )
        op.add_column(u'action', sa.Column('post_id', sa.Integer(), nullable=False))
        op.add_column(u'action', sa.Column('type', sa.Unicode(length=255), nullable=False))
        op.drop_column(u'action', u'verb')
        ### end Alembic commands ###

    # Do stuff with the app's models here.
    with transaction.manager:
        pass


def downgrade(pyramid_env):
    with context.begin_transaction():
        ### commands auto generated by Alembic - please adjust! ###
        op.add_column(u'action', sa.Column(u'verb', sa.VARCHAR(length=255), nullable=False))
        op.drop_column(u'action', 'type')
        op.drop_column(u'action', 'post_id')
        op.drop_table('view')
        op.drop_table('expand')
        op.drop_table('collapse')
        ### end Alembic commands ###
