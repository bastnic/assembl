""" Pyramid add start-up module. """

from pyramid.config import Configurator
from pyramid.authentication import SessionAuthenticationPolicy
from pyramid.authorization import ACLAuthorizationPolicy
from pyramid_beaker import session_factory_from_settings
from sqlalchemy import engine_from_config

from .db import DBSession
from .auth.models import Role, UserRole, LocalUserRole
from .synthesis.models import Discussion

from assembl.source.models import Post
from assembl.lib.models import CustomFieldsSASchema

def authentication_callback(userid, request):
    roles = DBSession.query(Role.name).join(UserRole).filter(
        UserRole.user_id == userid).all()
    roles = {x[0] for x in roles}
    # TODO: Get the discussion from the request
    discussion = DBSession.query(Discussion).first()
    if discussion:
        local_roles = DBSession.query(Role.name).join(LocalUserRole).filter(
            LocalUserRole.user_id == userid and
            LocalUserRole.discussion_id == discussion.id).all()
        roles.update({x[0] for x in local_roles})
    return list(roles)


def main(global_config, **settings):
    """ Return a Pyramid WSGI application. """
    Post.__ca__ = CustomFieldsSASchema(Post)

    settings['config_uri'] = global_config['__file__']

    # velruse requires session support
    session_factory = session_factory_from_settings(
        settings
        )
    # here we create the engine and bind it to the (not really a) session
    # factory called DBSession.
    engine = engine_from_config(settings, 'sqlalchemy.')
    DBSession.configure(bind=engine)
    
    config = Configurator(settings=settings)
    config.set_session_factory(session_factory)
    auth_policy = SessionAuthenticationPolicy(callback=authentication_callback)
    config.set_authentication_policy(auth_policy)
    config.set_authorization_policy(ACLAuthorizationPolicy())
    config.add_static_view('static', 'static', cache_max_age=3600)
    config.include('cornice')  # REST services library.
    # config.include('.lib.alembic')
    # config.include('.lib.email')
    config.include('.views')

    # config.scan('.lib')
    config.scan('.views')

    # jinja2
    config.include('pyramid_jinja2')

    # Mailer
    config.include('pyramid_mailer')

    # Contains a ApplicationCreated subscriber
    config.scan('assembl.lib.models')
    return config.make_wsgi_app()
