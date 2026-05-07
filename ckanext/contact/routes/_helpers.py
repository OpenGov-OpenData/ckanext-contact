# !/usr/bin/env python
# encoding: utf-8
#
# This file is part of ckanext-contact
# Created by the Natural History Museum in London, UK
import logging
import socket
from datetime import datetime, timezone

from ckan import logic
from ckan.common import asbool
from ckan.lib import mailer
from ckan.lib.navl.dictization_functions import unflatten
from ckan.plugins import PluginImplementations, toolkit
from pyisemail import is_email
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from ckanext.contact import recaptcha
from ckanext.contact.interfaces import IContact

log = logging.getLogger(__name__)


def clean_referrer_url(url, contact_path='/contact'):
    """
    Remove Cloudflare challenge query parameters from a URL. If the cleaned URL
    is just the contact page itself return an empty string.

    :param url: the referrer URL to clean
    :param contact_path: the path of the contact page to detect self-references
    :returns: the cleaned URL, or empty string if the URL is empty or self-referencing
    """
    if not url:
        return ''
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query, keep_blank_values=True)
        cleaned_params = {k: v for k, v in params.items() if not k.startswith('__cf_chl_')}
        cleaned_url = urlunparse(parsed._replace(query=urlencode(cleaned_params, doseq=True)))
        cleaned_parsed = urlparse(cleaned_url)
        if (
            cleaned_parsed.path.rstrip('/') == contact_path.rstrip('/')
            and not cleaned_params
        ):
            return ''
        return cleaned_url
    except Exception:
        return ''


def validate(data_dict):
    """
    Validates the given data and recaptcha if necessary.

    :param data_dict: the request params as a dict
    :returns: a 3-tuple of errors, error summaries and a recaptcha error, in the event
        where no issues occur the return is ({}, {}, None)
    """
    errors = {}
    error_summary = {}
    optional_fields = {'subject', 'referrer_url'}
    recaptcha_error = None

    # check each field to see if it has a value and if not, show and error
    for field, value in data_dict.items():
        # we know the save field is not necessary and may be empty so ignore it
        if field == 'save':
            continue
        # ignore optionals
        if field in optional_fields:
            continue
        if value is None or value == '':
            errors[field] = ['Missing Value']
            error_summary[field] = 'Missing value'

    # check the email address, if there is one and the config option isn't off
    if (
        toolkit.asbool(toolkit.config.get('ckanext.contact.check_email', True))
        and data_dict['email']
    ):
        if not is_email(data_dict['email'], check_dns=True):
            errors['email'] = ['Email address appears to be invalid']
            error_summary['email'] = 'Email address appears to be invalid'

    # clean and validate referrer_url
    referrer_url_raw = data_dict.get('referrer_url', '')
    if isinstance(referrer_url_raw, list):
        referrer_url_raw = referrer_url_raw[0] if referrer_url_raw else ''
    referrer_url = clean_referrer_url(referrer_url_raw.strip())
    if referrer_url:
        site_url = toolkit.config.get('ckan.site_url', '')
        if site_url and not referrer_url.startswith(site_url):
            referrer_url = ''
    data_dict['referrer_url'] = referrer_url

    # only check the recaptcha if there are no errors
    if not errors:
        try:
            expected_action = toolkit.config.get('ckanext.contact.recaptcha_v3_action')
            # check the recaptcha value, this only does anything if recaptcha is setup
            recaptcha.check_recaptcha(
                data_dict.get('g-recaptcha-response', None), expected_action
            )
        except recaptcha.RecaptchaError as e:
            log.info(f'Recaptcha failed due to "{e}"')
            recaptcha_error = toolkit._('Recaptcha check failed, please try again.')

    return errors, error_summary, recaptcha_error


def build_subject(
    subject=None, default='Contact/Question from visitor', timestamp_default=False
):
    """
    Creates the subject line for the contact email using the config or the provided
    subject.

    :param subject: a user defined subject line
    :param default: the default str to use if the user didn't provide a subject or
        ckanext.contact.subject isn't specified
    :param timestamp_default: the default bool to use if add_timestamp_to_subject isn't
        specified
    :returns: the subject line
    """
    if not subject:
        subject = toolkit.config.get('ckanext.contact.subject', toolkit._(default))
    if asbool(
        toolkit.config.get(
            'ckanext.contact.add_timestamp_to_subject', timestamp_default
        )
    ):
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S %Z')
        subject = f'{subject} [{timestamp}]'

    prefix = toolkit.config.get('ckanext.contact.subject_prefix', '')

    return f'{prefix}{" " if prefix else ""}{subject}'


def get_dataset_title_from_url(url):
    """
    Try to extract the dataset title from a CKAN URL.

    :param url: the URL to parse
    :return: dataset title if successful, None on any error
    """
    if not url:
        return None

    try:
        # Extract package identifier from URL
        parsed_url = urlparse(url)
        path_parts = parsed_url.path.split('/')
        if len(path_parts) >= 3 and path_parts[1] == 'dataset':
            package_id = path_parts[2]
        else:
            return None

        if not package_id:
            return None

        # Fetch dataset title using package_show action
        context = {'ignore_auth': True}
        package_dict = toolkit.get_action('package_show')(context, {'id': package_id})
        return package_dict.get('title')
    except Exception:
        return None


def submit():
    """
    Take the data in the request params and send an email using them. If the data is
    invalid or a recaptcha is setup and it fails, don't send the email.

    :returns: a dict of details
    """
    # this variable holds the status of sending the email
    email_success = True

    # pull out the data from the request
    data_dict = logic.clean_dict(
        unflatten(logic.tuplize_dict(logic.parse_params(toolkit.request.values)))
    )

    # validate the request params
    errors, error_summary, recaptcha_error = validate(data_dict)

    # if there are not errors and no recaptcha error, attempt to send the email
    if len(errors) == 0 and recaptcha_error is None:
        body_parts = [
            f'{data_dict["content"]}\n',
            'Sent by:',
            f'  Name: {data_dict["name"]}',
            f'  Email: {data_dict["email"]}',
        ]
        # include referrer URL if available
        referrer_url = data_dict.get('referrer_url', '').strip()
        if referrer_url:
            body_parts.append(f'  Referrer URL: {referrer_url}')
            # try to get dataset title if referrer_url is from a dataset
            dataset_title = get_dataset_title_from_url(referrer_url)
            if dataset_title:
                body_parts.append(f'  Dataset Title: {dataset_title}')
        mail_dict = {
            'recipient_email': toolkit.config.get(
                'ckanext.contact.mail_to', toolkit.config.get('email_to')
            ),
            'recipient_name': toolkit.config.get(
                'ckanext.contact.recipient_name', toolkit.config.get('ckan.site_title')
            ),
            'subject': build_subject(subject=data_dict.get('subject')),
            'body': '\n'.join(body_parts),
            'headers': {'reply-to': data_dict['email']},
        }

        # allow other plugins to modify the mail_dict
        for plugin in PluginImplementations(IContact):
            plugin.mail_alter(mail_dict, data_dict)

        # note the pop here so that we don't get parameter clashes when we call
        # mail_recipient below
        emails = mail_dict.pop('recipient_email')
        names = mail_dict.pop('recipient_name')
        if isinstance(emails, str):
            emails = [emails]
            names = [names]

        # send the email to each name/email pair
        for name, email in zip(names, emails):
            try:
                mailer.mail_recipient(name, email, **mail_dict)
            except (mailer.MailerException, socket.error):
                email_success = False

    return {
        'success': recaptcha_error is None and len(errors) == 0 and email_success,
        'data': data_dict,
        'errors': errors,
        'error_summary': error_summary,
        'recaptcha_error': recaptcha_error,
    }
