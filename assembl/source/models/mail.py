# coding=UTF-8
import email
import re
import smtplib
from cgi import escape as html_escape

from email.header import decode_header as decode_email_header, Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parseaddr
import jwzthreading

from bs4 import BeautifulSoup, Comment

from pyramid.threadlocal import get_current_registry

from datetime import datetime
from time import mktime
from imaplib2 import IMAP4_SSL, IMAP4
import transaction

from sqlalchemy.orm import relationship, backref, deferred
from sqlalchemy.orm import joinedload_all
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy import (
    Column,
    Integer,
    ForeignKey,
    String,
    Unicode,
    Binary,
    UnicodeText,
    DateTime,
    Boolean,
    or_,
    func,
)

from assembl.source.models.generic import Source, Content
from assembl.source.models.post import Post
from assembl.auth.models import EmailAccount
from assembl.tasks.imap import import_mails
from assembl.lib.sqla import mark_changed


class Mailbox(Source):
    """
    A Mailbox refers to an Email inbox that can be accessed with IMAP, and
    whose messages should be imported and displayed as Posts.
    """
    __tablename__ = "mailbox"
    id = Column(Integer, ForeignKey(
        'source.id',
        ondelete='CASCADE'
    ), primary_key=True)

    host = Column(String(1024), nullable=False)
    port = Column(Integer, nullable=False)
    username = Column(UnicodeText, nullable=False)
    #Note:  If using STARTTLS, this should be set to false
    use_ssl = Column(Boolean, default=True)
    password = Column(UnicodeText, nullable=False)
    folder = Column(UnicodeText, default=u"INBOX", nullable=False)

    last_imported_email_uid = Column(UnicodeText)
    subject_mangling_regex = Column(UnicodeText, nullable=True)
    subject_mangling_replacement = Column(UnicodeText, nullable=True)
    __compiled_subject_mangling_regex = None

    def _compile_subject_mangling_regex(self):
        if(self.subject_mangling_regex):
            self.__compiled_subject_mangling_regex =\
                re.compile(self.subject_mangling_regex)
        else:
            self.__compiled_subject_mangling_regex = None

    __mapper_args__ = {
        'polymorphic_identity': 'mailbox',
    }

    def mangle_mail_subject(self, subject):
        if self.__compiled_subject_mangling_regex is None:
            self._compile_subject_mangling_regex()

        if self.__compiled_subject_mangling_regex:
            if self.subject_mangling_replacement:
                repl = self.subject_mangling_replacement
            else:
                repl = ''
            (retval, num) =\
                self.__compiled_subject_mangling_regex.subn(repl, subject)
            return retval
        else:
            return subject

    VALID_TAGS = ['strong', 'em', 'p', 'ul', 'li', 'br']

    @staticmethod
    def sanitize_html(html_value, valid_tags=VALID_TAGS):
        soup = BeautifulSoup(html_value)
        comments = soup.findAll(text=lambda text:isinstance(text, Comment))
        [comment.extract() for comment in comments]
        for tag in soup.find_all(True):
            if tag.name not in valid_tags:
                tag.hidden = True

        return soup.decode_contents()

    @staticmethod
    def body_as_html(text_value):
        text_value = html_escape(text_value)
        text_value = text_value.replace("\r", '').replace("\n", "<br />")
        return text_value


    def parse_email(self, message_string, existing_email=None):
        parsed_email = email.message_from_string(message_string)
        body = None

        def get_plain_text_payload(message):
            """ Returns the first text/plain body as a unicode object, falling back to text/html body """

            def process_part(part, default_charset, text_part, html_part):
                if part.is_multipart():
                    for part in part.get_payload():
                        charset = part.get_content_charset(default_charset)
                        (text_part, html_part) = process_part(
                            part, charset, text_part, html_part)
                else:
                    charset = part.get_content_charset(default_charset)
                    decoded_part = part.get_payload(decode=True)
                    decoded_part = decoded_part.decode(charset, 'replace')
                    if part.get_content_type() == 'text/plain' and text_part is None:
                        text_part = decoded_part
                    elif part.get_content_type() == 'text/html' and html_part is None:
                        html_part = decoded_part
                return (text_part, html_part)

            html_part = None
            text_part = None
            default_charset = message.get_charset() or 'ISO-8859-1'
            (text_part, html_part) = process_part(message, default_charset, text_part, html_part)
            if html_part:
                return self.sanitize_html(html_part)
            elif text_part:
                return self.body_as_html(text_part)
            else:
                return u"Sorry, no assembl-supported mime type found in message parts"

        body = get_plain_text_payload(parsed_email)

        def email_header_to_unicode(header_string):
            decoded_header = decode_email_header(header_string)
            default_charset = 'ASCII'

            text = ''.join(
                [
                    unicode(t[0], t[1] or default_charset) for t in
                    decoded_header
                ]
            )

            return text

        new_message_id = parsed_email.get('Message-ID', None)
        if new_message_id:
            new_message_id = email_header_to_unicode(
                new_message_id)

        new_in_reply_to = parsed_email.get('In-Reply-To', None)
        if new_in_reply_to:
            new_in_reply_to = email_header_to_unicode(
                new_in_reply_to)

        sender = email_header_to_unicode(parsed_email.get('From'))
        sender_name, sender_email = parseaddr(sender)
        sender_email_account = EmailAccount.get_or_make_profile(self.db, sender_email, sender_name)
        creation_date = datetime.utcfromtimestamp(
            mktime(email.utils.parsedate(parsed_email['Date'])))
        subject = email_header_to_unicode(parsed_email['Subject'])
        recipients = email_header_to_unicode(parsed_email['To'])
        body = body.strip()
        # Try/except for a normal situation is an antipattern,
        # but sqlalchemy doesn't have a function that returns
        # 0, 1 result or an exception
        try:
            email_object = self.db.query(Email).filter(
                Email.message_id == new_message_id,
                Email.source_id == self.id,
            ).one()
            if existing_email and existing_email != email_object:
                raise ValueError("The existing object isn't the same as the one found by message id")
            email_object.recipients = recipients
            email_object.sender = sender
            email_object.subject = subject
            email_object.creation_date = creation_date
            email_object.message_id = new_message_id
            email_object.in_reply_to = new_in_reply_to
            email_object.body = body
            email_object.full_message = message_string
        except NoResultFound:
            email_object = Email(
                post=Post(),
                recipients=recipients,
                sender=sender,
                subject=subject,
                creation_date=creation_date,
                message_id=new_message_id,
                in_reply_to=new_in_reply_to,
                body=body,
                full_message=message_string
            )
        email_object.post.creator = sender_email_account.profile
        email_object.source = self
        email_object = self.db.merge(email_object)
        return (email_object, parsed_email)
        
    """
    emails have to be a complete set
    """
    @staticmethod
    def thread_mails(emails):
        print('Threading...')
        emails_for_threading = []
        for mail in emails:
            email_for_threading = jwzthreading.make_message(email.message_from_string(mail.full_message))
            #Store our emailsubject, jwzthreading does not decode subject itself
            email_for_threading.subject = mail.subject
            #Store our email object pointer instead of the raw message text
            email_for_threading.message = mail
            emails_for_threading.append(email_for_threading)

        threaded_emails = jwzthreading.thread(emails_for_threading)

        # Output
        L = threaded_emails.items()
        L.sort()
        for subj, container in L:
            jwzthreading.print_container(container, 0, True)
            
        def update_threading(threaded_emails, parent=None):
            

            for container in threaded_emails:
                #jwzthreading.print_container(container)
                #print (repr(container))
                
                ##print "parent: "+repr(container.parent)
                ##print "children: "+repr(container.children)
                ##print("\nProcessing:  " + repr(container.message.subject) + " " + repr(container.message.message_id))
                

                if(container.message):
                    current_parent = container.message.message.post.parent
                    if(current_parent):
                        db_parent_message_id = current_parent.content.message_id
                    else:
                        db_parent_message_id = None

                    if parent:
                        if parent.message:
                            #jwzthreading strips the <>, re-add them
                            algorithm_parent_message_id = unicode("<"+parent.message.message_id+">")
                        else:
                            # Parent was a dummy container, we may need to handle this case better
                            # we just potentially lost sibbling relationships
                            algorithm_parent_message_id = None
                    else:
                        algorithm_parent_message_id = None
                    #print("Current parent from algorithm: " + repr(algorithm_parent_message_id))
                    #print("References: " + repr(container.message.references))
                    if algorithm_parent_message_id != db_parent_message_id:
                        # Don't reparent if the current parent isn't an email, the threading algorithm only considers mails
                        if current_parent == None or isinstance(current_parent.content, Email):
                            #print("UPDATING PARENT for :" + repr(container.message.message.message_id))
                            new_parent = parent.message.message.post if algorithm_parent_message_id else None
                            #print repr(new_parent)
                            container.message.message.post.set_parent(new_parent)
                    if current_parent and current_parent.content.source_id != container.message.message.source_id:
                        #This is to correct past mistakes in the database, remove it once everyone ran it benoitg 2013-11-20
                        print("UPDATING PARENT, BAD ORIGINAL SOURCE" + repr(current_parent.content.source_id) + " " + repr(container.message.message.source_id))
                        new_parent = parent.message.message.post if algorithm_parent_message_id else None
                        #print repr(new_parent)
                        container.message.message.post.set_parent(new_parent)
                        
                    update_threading(container.children, container)
                else:
                    #print "Current message ID: None, was a dummy container"
                    update_threading(container.children, parent)
                
        update_threading(threaded_emails.values())

    @staticmethod
    def reprocess_content(mailbox):
        """ Allows re-parsing all content as if it were imported for the first time
            but without re-hitting the source, or changing the object ids.
            Call when a code change would change the representation in the database
            """
        mailbox_id = mailbox.id
        emails = mailbox.db.query(Email).filter(
                Email.source_id == mailbox_id,
                ).options(joinedload_all(Email.post, Post.parent, Post.content))
        email_ids = [email.id for email in emails]
        for email_id in email_ids:
            session = Email.db()
            email = Email.get(id=email_id)
            (email_object, _) = mailbox.parse_email(email.full_message, email)
            session.add(email_object)
            
            transaction.commit()
            Email.db.remove()
            mailbox = Mailbox.get(id=mailbox_id)
        emails = mailbox.db.query(Email).filter(
                Email.source_id == mailbox_id,
                ).options(joinedload_all(Email.post, Post.parent, Post.content))
        mailbox.thread_mails(emails)
        
    def import_content(self, only_new=True):
        #Mailbox.do_import_content(self, only_new)
        import_mails.delay(self.id, only_new)

    @staticmethod
    def do_import_content(mbox, only_new=True):
        if mbox.use_ssl:
            mailbox = IMAP4_SSL(host=mbox.host.encode('utf-8'), port=mbox.port)
        else:
            mailbox = IMAP4(host=mbox.host.encode('utf-8'), port=mbox.port)
        if 'STARTTLS' in mailbox.capabilities:
            #Always use starttls if server supports it
            mailbox.starttls()
        mailbox.login(mbox.username, mbox.password)
        mailbox.select(mbox.folder)

        command = "ALL"

        if only_new and mbox.last_imported_email_uid:
            command = "(UID %s:*)" % mbox.last_imported_email_uid

        search_status, search_result = mailbox.uid('search', None, command)

        email_ids = search_result[0].split()

        if only_new and mbox.last_imported_email_uid:
            # discard the first message, it should be the last imported email.
            del email_ids[0]

        def import_email(mailbox_obj, email_id):
            session = Email.db()
            mailbox_obj = session.merge(mailbox_obj)
            status, message_data = mailbox.uid('fetch', email_id, "(RFC822)")
            for response_part in message_data:
                if isinstance(response_part, tuple):
                    message_string = response_part[1]

            (email_object, _) = mailbox_obj.parse_email(message_string)
            session.add(email_object)
            transaction.commit()
            mailbox_obj = Mailbox.get(id=mailbox_obj.id)

        if len(email_ids):
            new_emails = [import_email(mbox, email_id) for email_id in email_ids]

            mbox = Mailbox.get(id=mbox.id)
            mbox.last_imported_email_uid = \
                email_ids[len(email_ids)-1]

        # TODO: remove this line, the property `last_import` does not persist.
        mbox.last_import = datetime.utcnow()
        mark_changed()
        transaction.commit()

        mailbox.close()
        mailbox.logout()

        if len(email_ids):
            #We imported mails, we need to re-thread
            emails = self.db.query(Email).filter(
                Email.source_id == self.id,
                ).options(joinedload_all(Email.post, Post.parent, Post.content))

            self.thread_mails(emails)

    def most_common_recipient_address(self):
        """
        Find the most common recipient address of the contents of this emaila
        address. This address can, in most use-cases can be considered the
        mailing list address.
        """

        most_common_recipients = self.db.query(
            func.count(
                Email.recipients
            ),
            Email.recipients,
        ).filter(
            Email.source_id == self.id,
        ).group_by(Email.recipients)

        most_common_addresses = {}

        for frequency, recipients in most_common_recipients[:50]:
            address_match = re.compile(
                r'[\w\-][\w\-\.]+@[\w\-][\w\-\.]+[a-zA-Z]{1,4}'
            )

            for recipient_address in address_match.findall(recipients):
                if recipient_address in most_common_addresses.keys():
                    most_common_addresses[
                        recipient_address
                    ] += int(frequency)

                else:
                    most_common_addresses[recipient_address] = int(frequency)

        most_common_address = sorted(
            [
                (most_common_addresses[address], address) for address in
                most_common_addresses.keys()
            ], key=lambda pair: pair[0]
        )[-1][1]

        return most_common_address

    def get_send_address(self):
        """
        Get the email address to send a message to the discussion
        """
        return self.most_common_recipient_address()

    # The send method will be a common interface on all sources.
    def send(
        self,
        sender,
        message_body,
        html_body=None,
        subject='[Assembl]'
    ):
        """
        Send an email from the given sender to the most common recipient in
        emails from this mailbox.
        """

        sent_from = ' '.join([
            "%(sender_name)s on Assembl" % {
                "sender_name": sender.display_name()
            },
            "<%(sender_email)s>" % {
                "sender_email": sender.get_preferred_email(),
            }
        ])

        if type(message_body) == 'str':
            message_body = message_body.decode('utf-8')

        recipients = self.get_send_address()

        message = MIMEMultipart('alternative')
        message['Subject'] = Header(subject, 'utf-8')
        message['From'] = sent_from

        message['To'] = recipients

        plain_text_body = message_body
        html_body = html_body or message_body

        # TODO: The plain text and html parts of the email should be different,
        # but we'll see what we can get from the front-end.

        plain_text_part = MIMEText(
            plain_text_body.encode('utf-8'),
            'plain',
            'utf-8'
        )

        html_part = MIMEText(
            html_body.encode('utf-8'),
            'html',
            'utf-8'
        )

        message.attach(plain_text_part)
        message.attach(html_part)

        smtp_connection = smtplib.SMTP(
            get_current_registry().settings['mail.host']
        )

        smtp_connection.sendmail(
            sent_from,
            recipients,
            message.as_string()
        )

        smtp_connection.quit()

    def serializable(self):
        serializable_source = super(Mailbox, self).serializable()

        serializable_source.update({
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "use_ssl": self.use_ssl,
            "folder": self.folder,
            "most_common_recipient_address":
            self.most_common_recipient_address()
        })

        return serializable_source

    def __repr__(self):
        return "<Mailbox %s>" % repr(self.name)


class MailingList(Mailbox):
    """
    A mailbox with mailing list semantics
    (single post address, subjetc mangling, etc.)
    """
    __tablename__ = "source_mailinglist"
    id = Column(Integer, ForeignKey(
        'mailbox.id',
        ondelete='CASCADE'
    ), primary_key=True)

    post_email_address = Column(UnicodeText, nullable=True)

    __mapper_args__ = {
        'polymorphic_identity': 'source_mailinglist',
    }

    def get_send_address(self):
        """
        Get the email address to send a message to the discussion
        """
        return self.post_email()


class Email(Content):
    """
    An Email refers to an email message that was imported from an Mailbox.
    """
    __tablename__ = "email"

    id = Column(Integer, ForeignKey(
        'content.id',
        ondelete='CASCADE'
    ), primary_key=True)

    # in virtuoso, varchar is 1024 bytes and sizeof(wchar)==4, so varchar is 256 chars
    recipients = deferred(Column(UnicodeText, nullable=False), group='raw_details')
    sender = deferred(Column(Unicode(), nullable=False), group='raw_details')
    subject = Column(Unicode(), nullable=False)
    body = Column(UnicodeText)

    full_message = deferred(Column(Binary), group='raw_details')

    message_id = Column(Unicode())
    in_reply_to = Column(Unicode())

    import_date = Column(DateTime, nullable=False, default=datetime.utcnow)

    __mapper_args__ = {
        'polymorphic_identity': 'email',
    }

    def __init__(self, *args, **kwargs):
        super(Email, self).__init__(*args, **kwargs)
        if self.subject.startswith('[synthesis]'):
            self.post.is_synthesis = True

    def reply(self, sender, response_body):
        """
        Send a response to this email.

        `sender` is a user instance.
        `response` is a string.
        """

        sent_from = ' '.join([
            "%(sender_name)s on Assembl" % {
                "sender_name": sender.display_name()
            },
            "<%(sender_email)s>" % {
                "sender_email": sender.get_preferred_email(),
            }
        ])

        if type(response_body) == 'str':
            response_body = response_body.decode('utf-8')

        recipients = self.recipients

        message = MIMEMultipart('alternative')
        message['Subject'] = Header(self.subject, 'utf-8')
        message['From'] = sent_from

        message['To'] = self.recipients
        message.add_header('In-Reply-To', self.message_id)

        plain_text_body = response_body
        html_body = response_body

        # TODO: The plain text and html parts of the email should be different,
        # but we'll see what we can get from the front-end.

        plain_text_part = MIMEText(
            plain_text_body.encode('utf-8'),
            'plain',
            'utf-8'
        )

        html_part = MIMEText(
            html_body.encode('utf-8'),
            'html',
            'utf-8'
        )

        message.attach(plain_text_part)
        message.attach(html_part)

        smtp_connection = smtplib.SMTP(
            get_current_registry().settings['mail.host']
        )

        smtp_connection.sendmail(
            sent_from,
            recipients,
            message.as_string()
        )

        smtp_connection.quit()

    def serializable(self):
        serializable_content = super(Email, self).serializable()

        serializable_content.update({
            "sender": self.sender,
            "creator": self.post.creator.serializable(),
            "recipients": self.recipients,
            "subject": self.subject,
            "body": self.body,
        })

        return serializable_content

    def __repr__(self):
        return "<Email '%s to %s'>" % (
            self.sender.encode('utf-8'),
            self.recipients.encode('utf-8')
        )

    def get_body(self):
        return self.body

    def get_title(self):
        return self.subject
