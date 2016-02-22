
import email
import uuid

from helpdesk.models import Queue, CustomField, FollowUp, Ticket, TicketCC
from django.test import TestCase
from django.core import mail
from django.core.exceptions import ObjectDoesNotExist
from django.forms import ValidationError
from django.test.client import Client
from django.core.urlresolvers import reverse

from helpdesk.management.commands.get_email import parse_mail_message, create_ticket_cc

try:  # python 3
    from urllib.parse import urlparse
except ImportError:  # python 2
    from urlparse import urlparse


class TicketBasicsTestCase(TestCase):
    fixtures = ['emailtemplate.json']

    def setUp(self):
        self.queue_public = Queue.objects.create(title='Queue 1', slug='q1', allow_public_submission=True, new_ticket_cc='new.public@example.com', updated_ticket_cc='update.public@example.com')
        self.queue_private = Queue.objects.create(title='Queue 2', slug='q2', allow_public_submission=False, new_ticket_cc='new.private@example.com', updated_ticket_cc='update.private@example.com')

        self.ticket_data = {
                'title': 'Test Ticket',
                'description': 'Some Test Ticket',
                }

        self.client = Client()

    def test_create_ticket_instance_from_payload(self):

        """
        Ensure that a <Ticket> instance is created whenever an email is sent to a public queue.
        """

        email_count = len(mail.outbox)
        ticket_data = dict(queue=self.queue_public, **self.ticket_data)
        ticket = Ticket.objects.create(**ticket_data)
        self.assertEqual(ticket.ticket_for_url, "q1-%s" % ticket.id)
        self.assertEqual(email_count, len(mail.outbox))

    def test_create_ticket_from_email_with_message_id(self):

        """
        Ensure that a <Ticket> instance is created whenever an email is sent to a public queue.
        Also, make sure that the RFC 2822 field "message-id" is stored on the <Ticket.submitter_email_id>
        field.
        """

        msg = email.message.Message()

        message_id = uuid.uuid4().hex
        submitter_email = 'foo@bar.py'
     
        msg.__setitem__('Message-ID', message_id)
        msg.__setitem__('Subject', self.ticket_data['title'])
        msg.__setitem__('From', submitter_email) 
        msg.__setitem__('To', self.queue_public.email_address)
        msg.__setitem__('Content-Type', 'text/plain;')
        msg.set_payload(self.ticket_data['description'])

        email_count = len(mail.outbox)
        #print email_count
        #for m in mail.outbox:
        #    print m.to, m.subject

        parse_mail_message(str(msg), self.queue_public, quiet=True)

        followup = FollowUp.objects.get(message_id=message_id)
        ticket = Ticket.objects.get(id=followup.ticket.id)

        self.assertEqual(ticket.ticket_for_url, "q1-%s" % ticket.id)

        # As we have created an Ticket from an email, we notify the sender (+1) 
        # and the new and update queues (+2)
        self.assertEqual(email_count + 1 + 2, len(mail.outbox))

    def test_create_ticket_from_email_without_message_id(self):

        """
        Ensure that a <Ticket> instance is created whenever an email is sent to a public queue.
        Also, make sure that the RFC 2822 field "message-id" is stored on the <Ticket.submitter_email_id>
        field.
        """

        msg = email.message.Message()
        submitter_email = 'foo@bar.py'

        msg.__setitem__('Subject', self.ticket_data['title'])
        msg.__setitem__('From', submitter_email) 
        msg.__setitem__('To', self.queue_public.email_address)
        msg.__setitem__('Content-Type', 'text/plain;')
        msg.set_payload(self.ticket_data['description'])

        email_count = len(mail.outbox)

        parse_mail_message(str(msg), self.queue_public, quiet=True)

        ticket = Ticket.objects.get(title=self.ticket_data['title'], queue=self.queue_public, submitter_email=submitter_email)

        self.assertEqual(ticket.ticket_for_url, "q1-%s" % ticket.id)

        # As we have created an Ticket from an email, we notify the sender (+1) 
        # and the new and update queues (+2)
        self.assertEqual(email_count + 1 + 2, len(mail.outbox))

    def test_create_ticket_from_email_with_carbon_copy(self):

        """ 
        Ensure that an instance of <TicketCC> is created for every valid element of the
        "rfc_2822_cc" field when creating a <Ticket> instance.
        """

        msg = email.message.Message()

        message_id = uuid.uuid4().hex
        submitter_email = 'foo@bar.py'
        cc_list = ['bravo@example.net', 'charlie@foobar.com']

        msg.__setitem__('Message-ID', message_id)
        msg.__setitem__('Subject', self.ticket_data['title'])
        msg.__setitem__('From', submitter_email)
        msg.__setitem__('To', self.queue_public.email_address)
        msg.__setitem__('Cc', ','.join(cc_list))
        msg.__setitem__('Content-Type', 'text/plain;')
        msg.set_payload(self.ticket_data['description'])

        email_count = len(mail.outbox)
        
        parse_mail_message(str(msg), self.queue_public, quiet=True)

        followup = FollowUp.objects.get(message_id=message_id)
        ticket = Ticket.objects.get(id=followup.ticket.id)
        self.assertEqual(ticket.ticket_for_url, "q1-%s" % ticket.id)

        # As we have created an Ticket from an email, we notify the sender (+1),
        # the new and update queues (+2) and contacts on the cc_list (+1 as it's 
        # treated as a list)
        self.assertEqual(email_count + 1 + 2 + 1, len(mail.outbox))

        # Ensure that <TicketCC> is created
        for cc_email in cc_list:
            ticket_cc = TicketCC.objects.get(ticket=ticket, email=cc_email)
            self.assertTrue(ticket_cc.ticket, ticket)
            self.assertTrue(ticket_cc.email, cc_email)

    def test_create_ticket_from_email_with_invalid_carbon_copy(self):

        """ 
        Ensure that no <TicketCC> instance is created if an invalid element of the
        "rfc_2822_cc" field is provided when creating a <Ticket> instance.
        """

        msg = email.message.Message()

        message_id = uuid.uuid4().hex
        submitter_email = 'foo@bar.py'
        cc_list = ['null@example', 'invalid@foobar']

        msg.__setitem__('Message-ID', message_id)
        msg.__setitem__('Subject', self.ticket_data['title'])
        msg.__setitem__('From', submitter_email)
        msg.__setitem__('To', self.queue_public.email_address)
        msg.__setitem__('Cc', ','.join(cc_list))
        msg.__setitem__('Content-Type', 'text/plain;')
        msg.set_payload(self.ticket_data['description'])

        email_count = len(mail.outbox)

        self.assertRaises(ValidationError, parse_mail_message, str(msg), self.queue_public, quiet=True)

    def test_create_followup_from_email_with_valid_message_id_with_when_no_initial_cc_list(self):

        """
        Ensure that if a message is received with an valid In-Reply-To ID, 
        the expected <TicketCC> instances are created even if the there were
        no <TicketCC>s so far.
        """

        ### Ticket and TicketCCs creation ###
        msg = email.message.Message()

        message_id = uuid.uuid4().hex
        submitter_email = 'foo@bar.py'

        msg.__setitem__('Message-ID', message_id)
        msg.__setitem__('Subject', self.ticket_data['title'])
        msg.__setitem__('From', submitter_email)
        msg.__setitem__('To', self.queue_public.email_address)
        msg.__setitem__('Content-Type', 'text/plain;')
        msg.set_payload(self.ticket_data['description'])

        email_count = len(mail.outbox)
        
        parse_mail_message(str(msg), self.queue_public, quiet=True)

        followup = FollowUp.objects.get(message_id=message_id)
        ticket = Ticket.objects.get(id=followup.ticket.id)
        ### end of the Ticket and TicketCCs creation ###

        # Reply message
        reply = email.message.Message()

        reply_message_id = uuid.uuid4().hex
        submitter_email = 'foo@bar.py'
        cc_list = ['bravo@example.net', 'charlie@foobar.com']

        reply.__setitem__('Message-ID', reply_message_id)
        reply.__setitem__('In-Reply-To', message_id)
        reply.__setitem__('Subject', self.ticket_data['title'])
        reply.__setitem__('From', submitter_email)
        reply.__setitem__('To', self.queue_public.email_address)
        reply.__setitem__('Cc', ','.join(cc_list))
        reply.__setitem__('Content-Type', 'text/plain;')
        reply.set_payload(self.ticket_data['description'])

        parse_mail_message(str(reply), self.queue_public, quiet=True)

        followup = FollowUp.objects.get(message_id=message_id)
        ticket = Ticket.objects.get(id=followup.ticket.id)
        self.assertEqual(ticket.ticket_for_url, "q1-%s" % ticket.id)

        # Ensure that <TicketCC> is created
        for cc_email in cc_list:
            # Even after 2 messages with the same cc_list, <get> MUST return only 
            # one object 
            ticket_cc = TicketCC.objects.get(ticket=ticket, email=cc_email)
            self.assertTrue(ticket_cc.ticket, ticket)
            self.assertTrue(ticket_cc.email, cc_email)

        # As we have created an Ticket from an email, we notify the sender (+1)
        # and the new and update queues (+2)
        expected_email_count = 1 + 2

        # As an update was made, we increase the expected_email_count with:
        # cc_list: +1
        # public_update_queue: +1
        expected_email_count += 1 + 1   
        self.assertEqual(expected_email_count, len(mail.outbox))


    def test_create_followup_from_email_with_valid_message_id_with_original_cc_list_included(self):

        """
        Ensure that if a message is received with an valid In-Reply-To ID, 
        the expected <TicketCC> instances are created but if there's any 
        overlap with the previous Cc list, no duplicates are created.
        """

        ### Ticket and TicketCCs creation ###
        msg = email.message.Message()

        message_id = uuid.uuid4().hex
        submitter_email = 'foo@bar.py'
        cc_list = ['bravo@example.net', 'charlie@foobar.com']

        msg.__setitem__('Message-ID', message_id)
        msg.__setitem__('Subject', self.ticket_data['title'])
        msg.__setitem__('From', submitter_email)
        msg.__setitem__('To', self.queue_public.email_address)
        msg.__setitem__('Cc', ','.join(cc_list))
        msg.__setitem__('Content-Type', 'text/plain;')
        msg.set_payload(self.ticket_data['description'])

        email_count = len(mail.outbox)
        
        parse_mail_message(str(msg), self.queue_public, quiet=True)

        followup = FollowUp.objects.get(message_id=message_id)
        ticket = Ticket.objects.get(id=followup.ticket.id)

        # Ensure that <TicketCC> is created
        for cc_email in cc_list:
            ticket_cc = TicketCC.objects.get(ticket=ticket, email=cc_email)
            self.assertTrue(ticket_cc.ticket, ticket)
            self.assertTrue(ticket_cc.email, cc_email)
            self.assertTrue(ticket_cc.can_view, True)

        # As we have created an Ticket from an email, we notify the sender (+1),
        # the new and update queues (+2) and contacts on the cc_list (+1 as it's 
        # treated as a list)
        self.assertEqual(email_count + 1 + 2 + 1, len(mail.outbox))
        ### end of the Ticket and TicketCCs creation ###

        # Reply message
        reply = email.message.Message()

        reply_message_id = uuid.uuid4().hex
        submitter_email = 'foo@bar.py'
        cc_list = ['bravo@example.net', 'charlie@foobar.com']

        reply.__setitem__('Message-ID', reply_message_id)
        reply.__setitem__('In-Reply-To', message_id)
        reply.__setitem__('Subject', self.ticket_data['title'])
        reply.__setitem__('From', submitter_email)
        reply.__setitem__('To', self.queue_public.email_address)
        reply.__setitem__('Cc', ','.join(cc_list))
        reply.__setitem__('Content-Type', 'text/plain;')
        reply.set_payload(self.ticket_data['description'])
       
        parse_mail_message(str(reply), self.queue_public, quiet=True)

        followup = FollowUp.objects.get(message_id=message_id)
        ticket = Ticket.objects.get(id=followup.ticket.id)
        self.assertEqual(ticket.ticket_for_url, "q1-%s" % ticket.id)

        # Ensure that <TicketCC> is created
        for cc_email in cc_list:
            # Even after 2 messages with the same cc_list, 
            # <get> MUST return only one object 
            ticket_cc = TicketCC.objects.get(ticket=ticket, email=cc_email)
            self.assertTrue(ticket_cc.ticket, ticket)
            self.assertTrue(ticket_cc.email, cc_email)

        # As we have created an Ticket from an email, we notify the sender (+1),
        # the new and update queues (+2) and contacts on the cc_list (+1 as it's 
        # treated as a list)
        expected_email_count = 1 + 2 + 1

        # As an update was made, we increase the expected_email_count with:
        # cc_list: +1
        # public_update_queue: +1
        expected_email_count += 1 + 1   
        self.assertEqual(expected_email_count, len(mail.outbox))

    def test_create_followup_from_email_with_invalid_message_id(self):

        """
        Ensure that if a message is received with an invalid In-Reply-To ID and we
        can infer the original Ticket ID by the message's subject, the expected 
        <TicketCC> instances are created
        """
        
        ### Ticket and TicketCCs creation ###
        msg = email.message.Message()

        message_id = uuid.uuid4().hex
        submitter_email = 'foo@bar.py'
        cc_list = ['bravo@example.net', 'charlie@foobar.com']

        msg.__setitem__('Message-ID', message_id)
        msg.__setitem__('Subject', self.ticket_data['title'])
        msg.__setitem__('From', submitter_email)
        msg.__setitem__('To', self.queue_public.email_address)
        msg.__setitem__('Cc', ','.join(cc_list))
        msg.__setitem__('Content-Type', 'text/plain;')
        msg.set_payload(self.ticket_data['description'])

        email_count = len(mail.outbox)
        
        parse_mail_message(str(msg), self.queue_public, quiet=True)

        followup = FollowUp.objects.get(message_id=message_id)
        ticket = Ticket.objects.get(id=followup.ticket.id)

        # Ensure that <TicketCC> is created
        for cc_email in cc_list:
            ticket_cc = TicketCC.objects.get(ticket=ticket, email=cc_email)
            self.assertTrue(ticket_cc.ticket, ticket)
            self.assertTrue(ticket_cc.email, cc_email)
            self.assertTrue(ticket_cc.can_view, True)

        # As we have created an Ticket from an email, we notify the sender (+1),
        # the new and update queues (+2) and contacts on the cc_list (+1 as it's 
        # treated as a list)
        self.assertEqual(email_count + 1 + 2 + 1, len(mail.outbox))
        ### end of the Ticket and TicketCCs creation ###

        # Reply message
        reply = email.message.Message()

        reply_message_id = uuid.uuid4().hex
        submitter_email = 'foo@bar.py'
        cc_list = ['bravo@example.net', 'charlie@foobar.com']

        invalid_message_id = 'INVALID'
        reply_subject = 'Re: ' + self.ticket_data['title']

        reply.__setitem__('Message-ID', reply_message_id)
        reply.__setitem__('In-Reply-To', invalid_message_id)
        reply.__setitem__('Subject', reply_subject)
        reply.__setitem__('From', submitter_email)
        reply.__setitem__('To', self.queue_public.email_address)
        reply.__setitem__('Cc', ','.join(cc_list))
        reply.__setitem__('Content-Type', 'text/plain;')
        reply.set_payload(self.ticket_data['description'])

        email_count = len(mail.outbox)
        
        parse_mail_message(str(reply), self.queue_public, quiet=True)

        followup = FollowUp.objects.get(message_id=message_id)
        ticket = Ticket.objects.get(id=followup.ticket.id)
        self.assertEqual(ticket.ticket_for_url, "q1-%s" % ticket.id)

        # Ensure that <TicketCC> is created
        for cc_email in cc_list:
            # Even after 2 messages with the same cc_list, <get> MUST return only 
            # one object 
            ticket_cc = TicketCC.objects.get(ticket=ticket, email=cc_email)
            self.assertTrue(ticket_cc.ticket, ticket)
            self.assertTrue(ticket_cc.email, cc_email)

        # As we have created an Ticket from an email, we notify the sender (+1),
        # the new and update queues (+2) and contacts on the cc_list (+1 as it's 
        # treated as a list)
        self.assertEqual(email_count + 1 + 2 + 1, len(mail.outbox))


    def test_create_ticket_public(self):
        email_count = len(mail.outbox)

        response = self.client.get(reverse('helpdesk_home'))
        self.assertEqual(response.status_code, 200)

        post_data = {
                'title': 'Test ticket title',
                'queue': self.queue_public.id,
                'submitter_email': 'ticket1.submitter@example.com',
                'body': 'Test ticket body',
                'priority': 3,
                }

        response = self.client.post(reverse('helpdesk_home'), post_data, follow=True)
        last_redirect = response.redirect_chain[-1]
        last_redirect_url = last_redirect[0]
        last_redirect_status = last_redirect[1]

        # Ensure we landed on the "View" page.
        # Django 1.9 compatible way of testing this
        # https://docs.djangoproject.com/en/1.9/releases/1.9/#http-redirects-no-longer-forced-to-absolute-uris
        urlparts = urlparse(last_redirect_url)
        self.assertEqual(urlparts.path, reverse('helpdesk_public_view'))

        # Ensure submitter, new-queue + update-queue were all emailed.
        self.assertEqual(email_count+3, len(mail.outbox))

    def test_create_ticket_private(self):
        email_count = len(mail.outbox)
        post_data = {
                'title': 'Private ticket test',
                'queue': self.queue_private.id,
                'submitter_email': 'ticket2.submitter@example.com',
                'body': 'Test ticket body',
                'priority': 3,
                }

        response = self.client.post(reverse('helpdesk_home'), post_data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(email_count, len(mail.outbox))
        self.assertContains(response, 'Select a valid choice.')

    def test_create_ticket_customfields(self):
        email_count = len(mail.outbox)
        queue_custom = Queue.objects.create(title='Queue 3', slug='q3', allow_public_submission=True, updated_ticket_cc='update.custom@example.com')
        custom_field_1 = CustomField.objects.create(name='textfield', label='Text Field', data_type='varchar', max_length=100, ordering=10, required=False, staff_only=False)
        post_data = {
                'queue': queue_custom.id,
                'title': 'Ticket with custom text field',
                'submitter_email': 'ticket3.submitter@example.com',
                'body': 'Test ticket body',
                'priority': 3,
                'custom_textfield': 'This is my custom text.',
                }

        response = self.client.post(reverse('helpdesk_home'), post_data, follow=True)

        custom_field_1.delete()
        last_redirect = response.redirect_chain[-1]
        last_redirect_url = last_redirect[0]
        last_redirect_status = last_redirect[1]
        
        # Ensure we landed on the "View" page.
        # Django 1.9 compatible way of testing this
        # https://docs.djangoproject.com/en/1.9/releases/1.9/#http-redirects-no-longer-forced-to-absolute-uris
        urlparts = urlparse(last_redirect_url)
        self.assertEqual(urlparts.path, reverse('helpdesk_public_view'))

        # Ensure only two e-mails were sent - submitter & updated.
        self.assertEqual(email_count+2, len(mail.outbox))
