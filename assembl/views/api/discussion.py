import json

from pyramid.httpexceptions import HTTPNotFound
# from . import acls

from cornice import Service

from assembl.views.api import API_DISCUSSION_PREFIX

from assembl.synthesis.models import Discussion


discussion = Service(
    name='discussion',
    path=API_DISCUSSION_PREFIX + '/',
    description="Manipulate a single Discussion object",
    renderer='json',
)


@discussion.get()
def get_discussion(request):
    discussion_id = request.matchdict['discussion_id']
    discussion = Discussion.get_instance(discussion_id)
    view_def = request.GET.get('view')

    if not discussion:
        raise HTTPNotFound(
            "Discussion with id '%s' not found." % discussion_id
        )

    if view_def:
        return discussion.generic_json(view_def)
    else:
        return discussion.serializable()
