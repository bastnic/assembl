import json

from math import ceil
from cornice import Service
from pyramid.httpexceptions import HTTPNotFound, HTTPUnauthorized
from pyramid.i18n import TranslationString as _
from pyramid.security import authenticated_userid

from sqlalchemy import func, Integer, String, text
from sqlalchemy.dialects.postgresql.base import ARRAY

from sqlalchemy.orm import aliased, joinedload, joinedload_all, contains_eager
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.sql.expression import literal_column, bindparam, and_
from sqlalchemy.sql import cast

from assembl.views.api import API_DISCUSSION_PREFIX
import transaction

from assembl.auth import P_READ, P_ADD_POST
from assembl.models import (
    get_database_id, get_named_object, AgentProfile, Post, Email,
    Discussion, Source, Content, Idea, ViewPost, User)
from . import acls


posts = Service(name='posts', path=API_DISCUSSION_PREFIX + '/posts',
                description="Post API following SIOC vocabulary as much as possible",
                renderer='json', acl=acls)

post = Service(name='post', path=API_DISCUSSION_PREFIX + '/posts/{id:.+}',
               description="Manipulate a single post",
               acl=acls)



def _get_idea_query(post, levels=None):
    """Return a query that includes the post and its following thread.


    Beware: we use a recursive query via a CTE and the PostgreSQL-specific
    ARRAY type. Blame this guy for that choice:
    http://explainextended.com/2009/09/24/adjacency-list-vs-nested-sets-postgresql/

    Also, that other guy provided insight into using CTE queries:
    http://stackoverflow.com/questions/11994092/how-can-i-perform-this-recursive-common-table-expression-in-sqlalchemy

    A literal column and an op complement nicely all this craziness.

    All I can say is SQLAlchemy kicks ass, and so does PostgreSQL.

    """
    level = literal_column('ARRAY[id]', type_=ARRAY(Integer))
    post = Post.db.query(post.__class__) \
                    .add_columns(level.label('level')) \
                    .filter(post.__class__.id == post.id) \
                    .cte(name='thread', recursive=True)
    post_alias = aliased(post, name='post')
    replies_alias = aliased(post.__class__, name='replies')
    cumul_level = post_alias.c.level.op('||')(replies_alias.id)
    parent_link = replies_alias.parent_id == post_alias.c.id
    children = Post.db.query(replies_alias).add_columns(cumul_level) \
                        .filter(parent_link)

    if levels:
        level_limit = func.array_upper(post_alias.c.level, 1) < levels
        children = children.filter(level_limit)

    return Post.db.query(post.union_all(children)).order_by(post.c.level)


@posts.get(permission=P_READ)
def get_posts(request):
    discussion_id = int(request.matchdict['discussion_id'])
    discussion = Discussion.get(id=int(discussion_id))
    if not discussion:
        raise HTTPNotFound(_("No discussion found with id=%s" % discussion_id))

    discussion.import_from_sources()

    user_id = authenticated_userid(request)

    DEFAULT_PAGE_SIZE = 25
    page_size = DEFAULT_PAGE_SIZE

    filter_names = [ 
        filter_name for filter_name \
        in request.GET.getone('filters').split(',') \
        if filter_name
    ] if request.GET.get('filters') else []

    try:
        page = int(request.GET.getone('page'))
    except (ValueError, KeyError):
        page = 1

    if page < 1:
        page = 1

    root_post_id = request.GET.getall('root_post_id')
    if root_post_id:
        root_post_id = get_database_id("Post", root_post_id[0])

    root_idea_id = request.GET.getall('root_idea_id')
    if root_idea_id:
        root_idea_id = get_database_id("Idea", root_idea_id[0])

    ids = request.GET.getall('ids')
    if ids:
        ids = [get_database_id("Post", id) for id in ids]

    view_def = request.GET.get('view')


    #Rename "inbox" to "unread", the number of unread messages for the current user.
    no_of_messages_viewed_by_user = Post.db.query(ViewPost).join(
        Post,
        Content,
        Source
    ).filter(
        Source.discussion_id == discussion_id,
        Content.source_id == Source.id,
        ViewPost.actor_id == user_id,
    ).count() if user_id else 0

    posts = Post.db.query(Post).join(
        Content,
        Source,
    ).filter(
        Source.discussion_id == discussion_id,
        Content.source_id == Source.id,
    )
    no_of_posts_to_discussion = posts.count()

    post_data = []

    if root_idea_id:
        if root_idea_id == Idea.ORPHAN_POSTS_IDEA_ID:
            ideas_query = Post.db.query(Post) \
                .filter(Post.id.in_(text(Idea._get_orphan_posts_statement(),
                                         bindparams=[bindparam('discussion_id', discussion_id)]
                                         )))
        else:
            ideas_query = Post.db.query(Post) \
                .filter(Post.id.in_(text(Idea._get_related_posts_statement(),
                                         bindparams=[bindparam('root_idea_id', root_idea_id)]
                                         )))
        posts = ideas_query.join(Content,
                                 Source,
                                 )
    elif root_post_id:
        root_post = Post.get(id=root_post_id)

        posts = posts.filter(
            (Post.ancestry.like(
            root_post.ancestry + cast(root_post.id, String) + ',%'
            ))
            |
            (Post.id==root_post.id)
            )
        #Benoitg:  For now, this completely garbles threading without intelligent
        #handling of pagination.  Disabling
        #posts = posts.limit(page_size).offset(data['startIndex']-1)
    elif ids:
        posts = posts.filter(Post.id.in_(ids))

    if user_id:
        posts = posts.outerjoin(ViewPost,
                    and_(ViewPost.actor_id==user_id, ViewPost.post_id==Post.id)
                )
        posts = posts.add_entity(ViewPost)
    posts = posts.options(contains_eager(Post.content, Content.source))
    posts = posts.options(joinedload_all(Post.creator, AgentProfile.user))

    posts = posts.order_by(Content.creation_date)

    if 'synthesis' in filter_names:
        posts = posts.filter(Post.is_synthesis==True)

    if user_id:
        for post, viewpost in posts:
            if view_def:
                serializable_post = post.generic_json(view_def)
            else:
                serializable_post = post.serializable()
            if viewpost:
                serializable_post['read'] = True
            else:
                serializable_post['read'] = False
                if root_post_id:
                    viewed_post = ViewPost(
                        actor_id=user_id,
                        post=post
                    )

                    Post.db.add(viewed_post)
            post_data.append(serializable_post)
    else:
        for post in posts:
            if view_def:
                serializable_post = post.generic_json(view_def)
            else:
                serializable_post = post.serializable()
            post_data.append(serializable_post)

    data = {}
    data["page"] = page
    data["inbox"] = no_of_posts_to_discussion - no_of_messages_viewed_by_user
    #What is "total", the total messages in the current context?
    #This gave wrong count, I don't know why. benoitg
    #data["total"] = discussion.posts().count()
    data["total"] = no_of_posts_to_discussion
    data["maxPage"] = max(1, ceil(float(data["total"])/page_size))
    #TODO:  Check if we want 1 based index in the api
    data["startIndex"] = (page_size * page) - (page_size-1)

    if data["page"] == data["maxPage"]:
        data["endIndex"] = data["total"]
    else:
        data["endIndex"] = data["startIndex"] + (page_size-1)
    data["posts"] = post_data

    return data


@post.get(permission=P_READ)
def get_post(request):
    post_id = request.matchdict['id']
    post = Post.get_instance(post_id)
    view_def = request.GET.get('view')

    if not post:
        raise HTTPNotFound("Post with id '%s' not found." % post_id)

    if view_def:
        return post.generic_json(view_def)
    else:
        return post.serializable()


@posts.post(permission=P_ADD_POST)
def create_post(request):
    """
    We use post, not put, because we don't know the id of the post
    """
    request_body = json.loads(request.body)
    user_id = authenticated_userid(request)
    user = Post.db.query(User).filter_by(id=user_id).one()

    message = request_body.get('message', None)
    html = request_body.get('html', None)
    reply_id = request_body.get('reply_id', None)
    subject = request_body.get('subject', None)

    if not user_id:
        raise HTTPUnauthorized()

    if not message:
        raise HTTPUnauthorized()

    if reply_id:
        post = Post.get_instance(reply_id)
        post.content.reply(user, message)

        return {"ok": True}

    discussion_id = request.matchdict['discussion_id']
    discussion = Discussion.get(id=int(discussion_id))

    subject = subject or discussion.topic

    if not discussion:
        raise HTTPNotFound(
            _("No discussion found with id=%s" % discussion_id)
        )

    for source in discussion.sources:
        source.send(user, message, subject=subject, html_body=html)

    return {"ok": True}
