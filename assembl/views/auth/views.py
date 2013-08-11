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
    AgentProfile, User)
from ...auth.password import format_token
from ...auth.operations import (
    get_identity_provider, send_confirmation_email, verify_email_token)
from ...db import DBSession

default_context = {
    'STATIC_URL': '/static/',
}


@view_config(
    route_name='logout',
    renderer='assembl:templates/login.jinja2',
)
def logout(request):
    forget(request)
    return dict(default_context, **{
        'login_url': login_url,
        'providers': request.registry.settings['login_providers'],
    })


@view_config(
    route_name='login',
    request_method='GET', http_cache=60,
    renderer='assembl:templates/login.jinja2',
)
@view_config(
    renderer='users/login.jinja2',
    context='pyramid.exceptions.Forbidden',
    permission=NO_PERMISSION_REQUIRED
)
def login_view(request):
    # TODO: In case of forbidden, get the URL and pass it along.
    return dict(default_context, **{
        'login_url': login_url,
        'providers': request.registry.settings['login_providers'],
    })


@view_config(route_name='profile')
def assembl_profile(request):
    id_type = request.matchdict.get('type').strip()
    identifier = request.matchdict.get('identifier').strip()
    user = None
    if id_type == 'u':
        user = DBSession.query(User).filter_by(username=identifier).first()
        if not user:
            raise HTTPNotFound()
        profile = user.profile
    elif id_type == 'id':
        try:
            id = int(identifier)
        except:
            raise HTTPNotFound()
        user = DBSession.query(User).get(id)
        if not user:
            raise HTTPNotFound()
        profile = user.profile
    elif id_type == 'email':
        account = DBSession.query(EmailAccount).filter_by(
            email=identifier).order_by(desc(EmailAccount.verified)).first()
        if not account:
            raise HTTPNotFound()
        profile = account.profile
    else:
        account = DBSession.query(IdentityProviderAccount).join(
            IdentityProvider).filter(
            IdentityProviderAccount.username == identifier and
            IdentityProvider.type == id_type).first()
        if not account:
            raise HTTPNotFound()
        profile = account.profile
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
                 user=DBSession.query(User).get(logged_in)))

    errors = []
    if save:
        user_id = user.id
        redirect = False
        username = request.params.get('username', '').strip()
        if username:
            print username
            # check if exists
            if DBSession.query(User).filter_by(username=username).count():
                errors.append(_('The username %s is already used') % (username,))
            else:
                user.username = username
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
            DBSession.add(email)
        transaction.commit()
        if redirect:
            raise HTTPFound('/user/u/'+username)
        user = DBSession.query(User).get(user_id)
    unverified_emails = [
        (ea, DBSession.query(EmailAccount).filter_by(
            email=ea.email, verified=True).first())
        for ea in user.profile.email_accounts if not ea.verified]
    return render_to_response(
        'assembl:templates/profile.jinja2',
        dict(default_context,
             error='<br />'.join(errors),
             unverified_emails=unverified_emails,
             providers=request.registry.settings['login_providers'],
             the_user=user,
             user=DBSession.query(User).get(logged_in)))


@view_config(
    route_name='register',
    permission=NO_PERMISSION_REQUIRED,
    renderer='assembl:templates/register.jinja2'
)
def assembl_register_view(request):
    if not request.params.get('email'):
        return default_context
    forget(request)
    name = request.params.get('name', '').strip()
    password = request.params.get('password', '').strip()
    password2 = request.params.get('password2', '').strip()
    email = request.params.get('email', '').strip()
    # Find agent account to avoid duplicates!
    if DBSession.query(EmailAccount).filter_by(
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
    DBSession.add(user)
    DBSession.add(email_account)
    DBSession.flush()
    userid = user.id
    send_confirmation_email(request, email_account)
    # TODO: Check that the email logic gets the proper locale. (send in URL?)
    headers = remember(request, user.id, tokens=format_token(user))
    request.response.headerlist.extend(headers)
    transaction.commit()
    # Redirect to profile page. TODO: Remember another URL
    # TODO: Tell them to expect an email.
    raise HTTPFound(location='/user/id/'+str(userid))


@view_config(
    route_name='login',
    request_method='POST',
    permission=NO_PERMISSION_REQUIRED,
    renderer='assembl:templates/login.jinja2'
)
def assembl_login_complete_view(request):
    # Check if proper authorization. Otherwise send to another page.
    identifier = request.params.get('identifier', '').strip()
    password = request.params.get('password', '').strip()
    logged_in = authenticated_userid(request)
    user = None
    if '@' in identifier:
        account = DBSession.query(EmailAccount).filter_by(
            email=identifier, verified=True).first()
        if account:
            user = account.profile.user
    else:
        user = DBSession.query(User).filter_by(username=identifier).first()

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
            if user.username:
                raise HTTPFound(location='/user/u/'+user.username)
            else:
                raise HTTPFound(location='/user/id/'+str(user.id))
    if not user.check_password(password):
        user.login_failures += 1
        #TODO: handle high failure count
        DBSession.add(user)
        transaction.commit()
        return dict(default_context,
                    error=_("Invalid user and password"))
    headers = remember(request, user.id, tokens=format_token(user))
    request.response.headerlist.extend(headers)
    # Redirect to profile page. TODO: Remember another URL
    if user.username:
        raise HTTPFound(location='/user/u/'+user.username)
    else:
        raise HTTPFound(location='/user/id/'+str(user.id))


@view_config(
    context='velruse.AuthenticationComplete'
)
def velruse_login_complete_view(request):
    context = request.context
    velruse_profile = context.profile
    logged_in = authenticated_userid(request)
    provider = get_identity_provider(context)
    # find or create IDP_Accounts
    idp_accounts = []
    new_idp_accounts = []
    velruse_accounts = velruse_profile['accounts']
    old_autoflush = DBSession.autoflush
    # sqla mislikes creating accounts before profiles, so delay
    DBSession.autoflush = False
    for velruse_account in velruse_accounts:
        if 'userid' in velruse_account:
            idp_account = DBSession.query(IdentityProviderAccount).filter_by(
                provider=provider,
                domain=velruse_account['domain'],
                userid=velruse_account['userid']
            ).first()
            if idp_account:
                idp_accounts.append(idp_account)
        elif 'username' in velruse_account:
            idp_account = DBSession.query(IdentityProviderAccount).filter_by(
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
        DBSession.add(idp_account)
    # find AgentProfile
    profile = None
    user = None
    profiles = list(set((a.profile for a in idp_accounts if a.profile)))
    # Maybe we already have a profile based on email
    if provider.trust_emails and 'verifiedEmail' in velruse_profile:
        email = velruse_profile['verifiedEmail']
        email_account = DBSession.query(EmailAccount).filter_by(
            email=email, verified=True).first()
        if email_account and email_account.profile:
            profiles.push(email_account.profile)
    # prefer profiles with verified users, then users, then oldest profiles
    profiles.sort(key=lambda p: (
        not(p.user and p.user.verified), not p.user, p.id))
    if logged_in:
        # NOTE: Must make sure that login page not available when
        # logged in as another account.
        user = DBSession.query(User).filter_by(id=logged_in).first()
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

        DBSession.add(profile)
        username = None
        usernames = set((a['preferredUsername'] for a in velruse_accounts
                         if 'preferredUsername' in a))
        for u in usernames:
            if not DBSession.query(User).filter_by(username=u).count():
                username = u
                break
        user = User(
            profile=profile,
            username=username,
            verified=True,
            last_login=datetime.now(),
            creation_date=datetime.now(),
            #timezone=velruse_profile['utcOffset'],   # TODO: needs parsing
            )
        DBSession.add(user)
    for idp_account in new_idp_accounts:
        idp_account.profile = profile
    # Now all accounts have a profile
    DBSession.autoflush = old_autoflush
    email_accounts = {ea.email: ea for ea in profile.email_accounts}
    # There may be new emails in the accounts
    if 'verifiedEmail' in velruse_profile:
        email = velruse_profile['verifiedEmail']
        if email in email_accounts:
            email_account = email_accounts[email]
            if provider.trust_emails and not email_account.verified:
                email_account.verified = True
                DBSession.add(email_account)
        else:
            email_account = EmailAccount(
                email=email,
                verified=provider.trust_emails,
                profile=profile
                )
            email_accounts[email] = email_account
            DBSession.add(email_account)
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
            DBSession.add(email)
    # Note that if an IdP account stops claiming an email, it "leaks".
    DBSession.flush()

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
    email = DBSession.query(EmailAccount).get(id)
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
    # TODO: token expiry
    if email and not email.verified:
        # maybe another profile already verified that email
        other_email_account = DBSession.query(EmailAccount).filter_by(
            email=email.email, verified=True).first()
        if other_email_account:
            profile = email.profile
            # We have two versions of the email, delete the unverified one
            DBSession.delete(email)
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
