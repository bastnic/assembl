"""annotator fragment information

Revision ID: 57951973d5ce
Revises: 3c125512a81f
Create Date: 2013-10-27 09:22:48.903848

"""

# revision identifiers, used by Alembic.
revision = '57951973d5ce'
down_revision = '3c125512a81f'

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.orm import lazyload
import transaction

from assembl.lib import config


def upgrade(pyramid_env):
    with context.begin_transaction():
        op.create_table(
            'text_fragment_identifier',
            sa.Column('id', sa.Integer, primary_key=True),
            sa.Column('extract_id', sa.Integer, sa.ForeignKey('extract.id')),
            sa.Column('xpath_start', sa.String),
            sa.Column('offset_start', sa.Integer),
            sa.Column('xpath_end', sa.String),
            sa.Column('offset_end', sa.Integer)
        )
        op.add_column('extract', sa.Column('annotation_text', sa.UnicodeText))

    # Do stuff with the app's models here.
    from assembl.models import Extract
    db = Extract.db()
    with transaction.manager:
        q =  db.execute('''
            SELECT extract.id, email.subject, email.body, post.id 
            FROM extract
            JOIN email ON (email.id = extract.source_id)
            JOIN content ON (email.id = content.id)
            JOIN post ON (post.content_id = email.id)
            WHERE content.type = 'email'
            ''')
        vals = {ex_id: (sub, body, postid) for (ex_id, sub, body, postid) in q}
        for extract in db.query(Extract).options(lazyload('*')).all():
            v = vals.get(extract.id)
            if v:
                tfi = extract._infer_text_fragment_inner(*v)
                if tfi:
                    db.add(tfi)


def downgrade(pyramid_env):
    with context.begin_transaction():
        op.drop_table('text_fragment_identifier')
        op.drop_column('extract', 'annotation_text')
