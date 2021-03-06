"""Replacing to and from addresses on email with recipients and sender respectively

Revision ID: 24e6f5182d75
Revises: 2e1a77e61fb3
Create Date: 2013-08-11 16:51:32.610567

"""

# revision identifiers, used by Alembic.
revision = '24e6f5182d75'
down_revision = '2e1a77e61fb3'

from alembic import context, op
import sqlalchemy as sa
import transaction

from assembl.lib import config


def upgrade(pyramid_env):
    with context.begin_transaction():
        ### commands auto generated by Alembic - please adjust! ###
        op.add_column('email', sa.Column('sender', sa.Unicode(length=1024)))
        op.add_column('email', sa.Column('recipients', sa.Unicode(length=1024)))
        ### end Alembic commands ###

        # Move data from old columns into new columns
        op.execute("UPDATE email SET sender=from_address")
        op.execute("UPDATE email SET recipients=to_address")

        # Make new columns non-nullable
        op.alter_column('email', 'sender', nullable=False)
        op.alter_column('email', 'recipients', nullable=False)

        # Drop old columns
        op.drop_column('email', 'from_address')
        op.drop_column('email', 'to_address')

    # Do stuff with the app's models here.
    with transaction.manager:
        pass


def downgrade(pyramid_env):
    with context.begin_transaction():
        # Add old columns
        op.add_column(
            'email', 
            sa.Column('from_address', sa.Unicode(length=1024))
        )

        op.add_column(
            'email', 
            sa.Column('to_address', sa.Unicode(length=1024))
        )

        # Move date from new columns to old columns
        op.execute("UPDATE email SET from_address=sender")
        op.execute("UPDATE email SET to_address=recipients")

        # Make old columns non-nullable
        op.alter_column('email', 'from_address', nullable=False)
        op.alter_column('email', 'to_address', nullable=False)

        ### commands auto generated by Alembic - please adjust! ###
        op.drop_column('email', 'recipients')
        op.drop_column('email', 'sender')
        ### end Alembic commands ###
