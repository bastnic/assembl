import json
from datetime import datetime

from pyramid.i18n import TranslationString as _

from pyramid.view import view_config
from pyramid.renderers import render_to_response
from pyramid.security import (
    remember,
    forget,
    authenticated_userid,
    NO_PERMISSION_REQUIRED
    )
from pyramid.httpexceptions import (
    HTTPUnauthorized,
    HTTPFound,
    HTTPNotFound,
    HTTPServerError
    )

from sqlalchemy import desc
from sqlalchemy.orm.exc import NoResultFound
import transaction

from velruse import login_url

from ...auth.models import (
    EmailAccount, IdentityProvider, IdentityProviderAccount,
    AgentProfile, User, Username)
from ...auth.password import format_token
from ...auth.operations import (
    get_identity_provider, send_confirmation_email, verify_email_token)
from ...lib import config

default_context = {
    'STATIC_URL': '/static/'
}


@view_config(
    route_name='logout',
    renderer='assembl:templates/login.jinja2',
)
def logout(request):
    forget(request)
    next_view = request.params.get('next_view') or '/login'
    return HTTPFound(next_view)


@view_config(
    route_name='login',
    request_method='GET', http_cache=60,
    renderer='assembl:templates/login.jinja2',
)
#The following was executed when calls to the frontend api calls were 
#made.  I don't know how to avoid this registration of the api paths.
#It returns a 200 status code which breaks the API
#@view_config(
#    renderer='assembl:templates/login.jinja2',
#    context='pyramid.exceptions.Forbidden',
#    permission=NO_PERMISSION_REQUIRED
#)
def login_view(request):
    # TODO: In case of forbidden, get the URL and pass it along.
    return dict(default_context, **{
        'login_url': login_url,
        'providers': request.registry.settings['login_providers'],
        'next_view': request.params.get('next_view', '/')
    })


def get_profile(request):
    id_type = request.matchdict.get('type').strip()
    identifier = request.matchdict.get('identifier').strip()
    user = None
    session = AgentProfile.db
    if id_type == 'u':
        username = session.query(Username).filter_by(username=identifier).first()
        if not username:
            raise HTTPNotFound()
        user = username.user
        profile = user.profile
    elif id_type == 'id':
        try:
            id = int(identifier)
        except:
            raise HTTPNotFound()
        profile = session.query(AgentProfile).get(id)
        if not profile:
            raise HTTPNotFound()
    elif id_type == 'email':
        account = session.query(EmailAccount).filter_by(
            email=identifier).order_by(desc(EmailAccount.verified)).first()
        if not account:
            raise HTTPNotFound()
        profile = account.profile
    else:
        account = session.query(IdentityProviderAccount).join(
            IdentityProvider).filter(
            IdentityProviderAccount.username == identifier and
            IdentityProvider.type == id_type).first()
        if not account:
            raise HTTPNotFound()
        profile = account.profile
    if profile and not user:
        user = profile.user
    return (user, profile)

@view_config(route_name='profile')
def assembl_profile(request):
    session = AgentProfile.db
    user, profile = get_profile(request)
    id_type = request.matchdict.get('type').strip()
    logged_in = authenticated_userid(request)
    save = request.method == 'POST'
    if logged_in and not user:
        user = profile.user
    # if some other user
    if not user or not logged_in or logged_in != user.id:
        if save:
            raise HTTPUnauthorized()
        # Add permissions to view a profile?
        return render_to_response(
            'assembl:templates/view_profile.jinja2',
            dict(default_context,
                 profile=profile,
                 user=logged_in and session.query(User).get(logged_in)))

    errors = []
    if save:
        user_id = user.id
        redirect = False
        username = request.params.get('username', '').strip()
        if username:
            # check if exists
            if session.query(Username).filter_by(username=username).count():
                errors.append(_('The username %s is already used') % (username,))
            else:
                session.add(Username(username=username, user=user))
                if id_type == 'u':
                    redirect = True
        name = request.params.get('name', '').strip()
        if name:
            user.profile.name = name
        p1, p2 = (request.params.get('password1', '').strip(),
                  request.params.get('password2', '').strip())
        if p1 != p2:
            errors.append(_('The passwords are not identical'))
        elif p1:
            user.set_password(p1)
        add_email = request.params.get('add_email', '').strip()
        if add_email:
            # TODO: Check it's a valid email.
            # No need to check presence since not validated yet
            email = EmailAccount(
                email=add_email, profile=user.profile)
            session.add(email)
        transaction.commit()
        if redirect:
            raise HTTPFound('/user/u/'+username)
        user = session.query(User).get(user_id)
    unverified_emails = [
        (ea, session.query(EmailAccount).filter_by(
            email=ea.email, verified=True).first())
        for ea in user.profile.email_accounts() if not ea.verified]
    return render_to_response(
        'assembl:templates/profile.jinja2',
        dict(default_context,
             error='<br />'.join(errors),
             unverified_emails=unverified_emails,
             providers=request.registry.settings['login_providers'],
             the_user=user,
             user=session.query(User).get(logged_in)))


@view_config(route_name='avatar')
def avatar(request):
    user, profile = get_profile(request)
    size = int(request.matchdict.get('size'))
    if profile:
        gravatar_url = profile.avatar_url(size, request.application_url)
        return HTTPFound(location=gravatar_url)
    default = config.get('avatar.default_image_url') or \
            request.application_url+'/static/img/icon/user.png'
    return HTTPFound(location=default)


@view_config(
    route_name='register',
    permission=NO_PERMISSION_REQUIRED,
    renderer='assembl:templates/register.jinja2'
)
def assembl_register_view(request):
    if not request.params.get('email'):
        return dict(default_context,
                    next_view=request.params.get('next_view', '/'))
    forget(request)
    session = AgentProfile.db
    name = request.params.get('name', '').strip()
    password = request.params.get('password', '').strip()
    password2 = request.params.get('password2', '').strip()
    email = request.params.get('email', '').strip()
    # Find agent account to avoid duplicates!
    if session.query(EmailAccount).filter_by(
        email=email, verified=True).count():
            return dict(default_context,
                        error=_("We already have a user with this email."))
    if password != password2:
        return dict(default_context,
                    error=_("The passwords should be identical"))

    #TODO: Validate password quality
    # otherwise create.
    profile = AgentProfile(
        name=name
        )
    user = User(
        profile=profile,
        password=password,
        creation_date=datetime.now()
        )
    email_account = EmailAccount(
        email=email,
        profile=profile
        )
    session.add(user)
    session.add(email_account)
    session.flush()
    userid = user.id
    send_confirmation_email(request, email_account)
    # TODO: Check that the email logic gets the proper locale. (send in URL?)
    headers = remember(request, user.id, tokens=format_token(user))
    request.response.headerlist.extend(headers)
    transaction.commit()
    # TODO: Tell them to expect an email.
    raise HTTPFound(location=request.params.get('next_view', '/'))


@view_config(
    route_name='login',
    request_method='POST',
    permission=NO_PERMISSION_REQUIRED,
    renderer='assembl:templates/login.jinja2'
)
def assembl_login_complete_view(request):
    # Check if proper authorization. Otherwise send to another page.
    session = AgentProfile.db
    identifier = request.params.get('identifier', '').strip()
    password = request.params.get('password', '').strip()
    logged_in = authenticated_userid(request)
    user = None
    if '@' in identifier:
        account = session.query(EmailAccount).filter_by(
            email=identifier, verified=True).first()
        if account:
            user = account.profile.user
    else:
        username = session.query(Username).filter_by(username=identifier).first()
        if username:
            user = username.user

    if not user:
        return dict(default_context,
                    error=_("This user cannot be found"))
    if logged_in:
        if user.id != logged_in:
            # logging in as a different user
            # Could I be combining account?
            forget(request)
        else:
            # re-logging in? Why?
            raise HTTPFound(location=request.params.get('next_view') or '/')
    if not user.check_password(password):
        user.login_failures += 1
        #TODO: handle high failure count
        session.add(user)
        transaction.commit()
        return dict(default_context,
                    error=_("Invalid user and password"))
    headers = remember(request, user.id, tokens=format_token(user))
    request.response.headerlist.extend(headers)
    raise HTTPFound(location=request.params.get('next_view') or '/')


@view_config(
    context='velruse.AuthenticationComplete'
)
def velruse_login_complete_view(request):
    session = AgentProfile.db
    context = request.context
    velruse_profile = context.profile
    logged_in = authenticated_userid(request)
    provider = get_identity_provider(context)
    # find or create IDP_Accounts
    idp_accounts = []
    new_idp_accounts = []
    velruse_accounts = velruse_profile['accounts']
    old_autoflush = session.autoflush
    # sqla mislikes creating accounts before profiles, so delay
    session.autoflush = False
    for velruse_account in velruse_accounts:
        if 'userid' in velruse_account:
            idp_account = session.query(IdentityProviderAccount).filter_by(
                provider=provider,
                domain=velruse_account['domain'],
                userid=velruse_account['userid']
            ).first()
            if idp_account:
                idp_accounts.append(idp_account)
        elif 'username' in velruse_account:
            idp_account = session.query(IdentityProviderAccount).filter_by(
                provider=provider,
                domain=velruse_account['domain'],
                username=velruse_account['username']
            ).first()
            if idp_account:
                idp_accounts.append(idp_account)
        else:
            raise HTTPServerError()
    if not idp_accounts:
        idp_account = IdentityProviderAccount(
            provider=provider,
            domain=velruse_account.get('domain'),
            userid=velruse_account.get('userid'),
            username=velruse_account.get('username')
            )
        idp_accounts.append(idp_account)
        new_idp_accounts.append(idp_account)
        session.add(idp_account)
    # find AgentProfile
    profile = None
    user = None
    profiles = list(set((a.profile for a in idp_accounts if a.profile)))
    # Maybe we already have a profile based on email
    if provider.trust_emails and 'verifiedEmail' in velruse_profile:
        email = velruse_profile['verifiedEmail']
        email_account = session.query(EmailAccount).filter_by(
            email=email, verified=True).first()
        if email_account and email_account.profile:
            profiles.push(email_account.profile)
    # prefer profiles with verified users, then users, then oldest profiles
    profiles.sort(key=lambda p: (
        not(p.user and p.user.verified), not p.user, p.id))
    if logged_in:
        # NOTE: Must make sure that login page not available when
        # logged in as another account.
        user = session.query(User).filter_by(id=logged_in).first()
        if user:
            profile = user.profile
            if profile in profiles:
                profiles.remove(profile)
            profiles.insert(0, user.profile)
    if len(profiles):
        # first is presumably best
        profile = profiles.pop(0)
        while len(profiles):
            # Multiple profiles. We need to combine them to one.
            profile.merge(profiles.pop())
        user = profile.user
        if user:
            username = profile.user.username
            user.last_login = datetime.now()
    else:
        # Create a new profile and user
        profile = AgentProfile(name=velruse_profile['displayName'])

        session.add(profile)
        username = None
        usernames = set((a['preferredUsername'] for a in velruse_accounts
                         if 'preferredUsername' in a))
        for u in usernames:
            if not session.query(Username).filter_by(username=u).count():
                username = u
                break
        user = User(
            profile=profile,
            verified=True,
            last_login=datetime.now(),
            creation_date=datetime.now(),
            #timezone=velruse_profile['utcOffset'],   # TODO: needs parsing
            )
        session.add(user)
        if username:
            session.add(Username(username=username, user=user))
    for idp_account in new_idp_accounts:
        idp_account.profile = profile
    # Now all accounts have a profile
    session.autoflush = old_autoflush
    email_accounts = {ea.email: ea for ea in profile.email_accounts()}
    # There may be new emails in the accounts
    if 'verifiedEmail' in velruse_profile:
        email = velruse_profile['verifiedEmail']
        if email in email_accounts:
            email_account = email_accounts[email]
            if provider.trust_emails and not email_account.verified:
                email_account.verified = True
                session.add(email_account)
        else:
            email_account = EmailAccount(
                email=email,
                verified=provider.trust_emails,
                profile=profile
                )
            email_accounts[email] = email_account
            session.add(email_account)
    for email in velruse_profile.get('emails', []):
        preferred = False
        if isinstance(email, dict):
            preferred = email.get('preferred', False)
            email = email['value']
        if email not in email_accounts:
            email = EmailAccount(
                email=email,
                preferred=preferred,
                profile=profile
                )
            session.add(email)
    # Note that if an IdP account stops claiming an email, it "leaks".
    session.flush()

    user_id = user.id
    headers = remember(request, user_id, tokens=format_token(user))
    request.response.headerlist.extend(headers)
    transaction.commit()
    # TODO: Store the OAuth etc. credentials.
    # Though that may be done by velruse?
    if username:
        raise HTTPFound(location='/user/u/'+username)
    else:
        raise HTTPFound(location='/user/id/'+str(user_id))


@view_config(
    route_name='confirm_user_email',
    permission=NO_PERMISSION_REQUIRED
)
def confirm_user_email(request):
    # TODO: How to make this not become a spambot?
    id = int(request.matchdict.get('email_account_id'))
    email = EmailAccount.get(id=id)
    if not email:
        raise HTTPNotFound()
    if not email.verified:
        send_confirmation_email(request, email)
    if email.profile.user:
        user = email.profile.user
        # TODO: Say we did it.
        if user.username:
            raise HTTPFound(location='/user/u/'+user.username)
        else:
            raise HTTPFound(location='/user/id/'+str(user.id))
    else:
        # we confirmed a profile without a user? Now what?
        raise HTTPServerError()


@view_config(
    route_name='user_confirm_email',
    permission=NO_PERMISSION_REQUIRED
)
def user_confirm_email(request):
    token = request.matchdict.get('ticket')
    email = verify_email_token(token)
    session = EmailAccount.db
    # TODO: token expiry
    if email and not email.verified:
        # maybe another profile already verified that email
        other_email_account = session.query(EmailAccount).filter_by(
            email=email.email, verified=True).first()
        if other_email_account:
            profile = email.profile
            # We have two versions of the email, delete the unverified one
            session.delete(email)
            if other_email_account.profile != email.profile:
                # Give priority to the one where the email was verified last.
                profile.merge(other_email_account.profile)
            email = other_email_account
        email.verified = True
        email.profile.verified = True
        user = None
        username = None
        userid = None
        if email.profile.user:
            user = email.profile.user
            username = user.username
            userid = user.id
        transaction.commit()
        if username:
            raise HTTPFound(location='/user/u/'+username)
        elif userid:
            raise HTTPFound(location='/user/id/'+str(userid))
        else:
            # we confirmed a profile without a user? Now what?
            raise HTTPServerError()
    else:
        raise HTTPUnauthorized("Wrong email token.")


@view_config(
    context='velruse.AuthenticationDenied',
    renderer='assembl:templates/login.jinja2',
)
def login_denied_view(request):
    return dict(default_context,
                error=_('Login failed, try again'))
    # TODO: If logged in otherwise, go to profile page. 
    # Otherwise, back to login page


def includeme(config):
    print "hello authviews"
    default_context['socket_url'] = \
        config.registry.settings['changes.websocket.url']
