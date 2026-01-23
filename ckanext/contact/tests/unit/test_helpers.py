from datetime import datetime, timezone

import pytest
from mock import patch, MagicMock
from freezegun import freeze_time

from ckanext.contact.routes._helpers import build_subject, get_dataset_title_from_url


class TestBuildSubject:
    def test_no_config_all_defaults(self):
        subject = build_subject()
        assert subject == 'Contact/Question from visitor'

    def test_no_config_pass_default_subject(self):
        default = 'TEST SUBJECT'

        subject = build_subject(default=default)
        assert subject == default

    def test_user_specified(self):
        subject = 'YES PLEASE EMAIL'
        assert build_subject(subject=subject) == subject

    @pytest.mark.ckan_config('ckanext.contact.subject', 'TEST SUBJECT')
    def test_user_specified_and_defaults(self):
        subject = 'YES PLEASE EMAIL'

        assert build_subject(subject=subject) == subject

    def test_no_config_pass_default_timestamp_false(self):
        timestamp_default = False

        subject = build_subject(timestamp_default=timestamp_default)
        assert subject == 'Contact/Question from visitor'

    @freeze_time('2021-01-01')
    def test_no_config_pass_default_timestamp_true(self):
        timestamp_default = True

        subject = build_subject(timestamp_default=timestamp_default)

        timestamp = datetime(2021, 1, 1, tzinfo=timezone.utc).strftime(
            '%Y-%m-%d %H:%M:%S %Z'
        )
        assert subject == f'Contact/Question from visitor [{timestamp}]'

    @freeze_time('2021-01-01')
    def test_no_config_pass_both(self):
        subject_default = 'TEST SUBJECT'
        timestamp_default = True

        subject = build_subject(
            default=subject_default, timestamp_default=timestamp_default
        )

        timestamp = datetime(2021, 1, 1, tzinfo=timezone.utc).strftime(
            '%Y-%m-%d %H:%M:%S %Z'
        )
        assert subject == f'{subject_default} [{timestamp}]'

    @freeze_time('2021-01-01')
    @pytest.mark.ckan_config('ckanext.contact.subject', 'TEST SUBJECT')
    @pytest.mark.ckan_config('ckanext.contact.add_timestamp_to_subject', 'true')
    def test_config_with_timestamp(self):
        subject = build_subject()

        timestamp = datetime(2021, 1, 1, tzinfo=timezone.utc).strftime(
            '%Y-%m-%d %H:%M:%S %Z'
        )
        assert subject == f'TEST SUBJECT [{timestamp}]'

    @pytest.mark.ckan_config('ckanext.contact.subject', 'TEST SUBJECT')
    @pytest.mark.ckan_config('ckanext.contact.add_timestamp_to_subject', 'false')
    def test_config_with_timestamp(self):
        subject = build_subject()
        assert subject == 'TEST SUBJECT'

    def test_prefix_not_provided(self):
        subject = build_subject(subject='TEST')
        assert subject == 'TEST'

    @pytest.mark.ckan_config('ckanext.contact.subject_prefix', 'PREFIX:')
    def test_prefix_provided(self):
        subject = build_subject(subject='TEST')
        assert subject == 'PREFIX: TEST'


class TestGetDatasetTitleFromUrl:
    @patch('ckanext.contact.routes._helpers.toolkit.get_action')
    def test_valid_dataset_url_returns_title(self, mock_get_action):
        mock_package_show = MagicMock(return_value={'title': 'Test Dataset Title'})
        mock_get_action.return_value = mock_package_show

        url = 'http://example.com/dataset/test-package-id'
        result = get_dataset_title_from_url(url)

        assert result == 'Test Dataset Title'
        mock_get_action.assert_called_once_with('package_show')
        mock_package_show.assert_called_once_with(
            {'ignore_auth': True}, {'id': 'test-package-id'}
        )

    @patch('ckanext.contact.routes._helpers.toolkit.get_action')
    def test_dataset_url_with_resource_returns_title(self, mock_get_action):
        mock_package_show = MagicMock(return_value={'title': 'Dataset with Resource'})
        mock_get_action.return_value = mock_package_show

        url = 'http://example.com/dataset/my-package/resource/resource-id'
        result = get_dataset_title_from_url(url)

        assert result == 'Dataset with Resource'
        mock_package_show.assert_called_once_with(
            {'ignore_auth': True}, {'id': 'my-package'}
        )

    def test_empty_url_returns_none(self):
        result = get_dataset_title_from_url('')
        assert result is None

    def test_none_url_returns_none(self):
        result = get_dataset_title_from_url(None)
        assert result is None

    def test_non_dataset_url_returns_none(self):
        result = get_dataset_title_from_url('http://example.com/organization/test')
        assert result is None

    def test_dataset_search_url_returns_none(self):
        result = get_dataset_title_from_url(
            'http://example.com/dataset/?organization=cabinet-office&license_id=notspecified'
        )
        assert result is None

    @patch('ckanext.contact.routes._helpers.toolkit.get_action')
    def test_package_show_exception_returns_none(self, mock_get_action):
        mock_package_show = MagicMock(side_effect=Exception('Dataset not found'))
        mock_get_action.return_value = mock_package_show

        url = 'http://example.com/dataset/non-existent-package'
        result = get_dataset_title_from_url(url)

        assert result is None
