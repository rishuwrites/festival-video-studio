import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "recap"))

import channel_branding


class ChannelBrandingTests(unittest.TestCase):
    def test_requires_explicit_confirmation_before_oauth_or_update(self):
        with mock.patch.object(channel_branding, "oauth_access_token") as oauth, \
                mock.patch.object(channel_branding.requests, "put") as put:
            with self.assertRaisesRegex(ValueError, "was not changed"):
                channel_branding.update_channel_branding(confirm=False)

        oauth.assert_not_called()
        put.assert_not_called()

    def test_updates_description_and_keywords_while_preserving_existing_branding(self):
        current = mock.Mock(status_code=200)
        current.json.return_value = {
            "items": [{
                "id": "channel123",
                "brandingSettings": {
                    "channel": {
                        "title": "Existing channel title",
                        "country": "IN",
                        "defaultLanguage": "hi",
                        "trackingAnalyticsAccountId": "analytics-id",
                    },
                },
            }],
        }
        updated = mock.Mock(status_code=200)
        with mock.patch.object(channel_branding, "oauth_access_token", return_value="token"), \
                mock.patch.object(
                    channel_branding.requests, "get", return_value=current,
                ) as get, \
                mock.patch.object(
                    channel_branding.requests, "put", return_value=updated,
                ) as put:
            channel_branding.update_channel_branding(
                description="भारत के त्योहार और परंपराएँ।",
                keywords="छठ पूजा, Indian festivals, छठ पूजा",
                confirm=True,
            )

        self.assertEqual(get.call_args.kwargs["params"], {
            "part": "brandingSettings,snippet", "mine": "true",
        })
        payload = put.call_args.kwargs["json"]
        channel = payload["brandingSettings"]["channel"]
        self.assertEqual(payload["id"], "channel123")
        self.assertEqual(channel["title"], "Existing channel title")
        self.assertEqual(channel["country"], "IN")
        self.assertEqual(channel["defaultLanguage"], "hi")
        self.assertEqual(channel["trackingAnalyticsAccountId"], "analytics-id")
        self.assertEqual(channel["description"], "भारत के त्योहार और परंपराएँ।")
        self.assertEqual(channel["keywords"], "छठ पूजा Indian festivals")

    def test_channel_update_error_names_required_oauth_scope(self):
        denied = mock.Mock(status_code=403)
        denied.json.return_value = {"error": {"message": "insufficient scopes"}}
        current = mock.Mock(status_code=200)
        current.json.return_value = {"items": [{"id": "channel123"}]}
        with mock.patch.object(channel_branding, "oauth_access_token", return_value="token"), \
                mock.patch.object(channel_branding.requests, "get", return_value=current), \
                mock.patch.object(channel_branding.requests, "put", return_value=denied):
            with self.assertRaisesRegex(RuntimeError, "youtube.force-ssl"):
                channel_branding.update_channel_branding(confirm=True)

    def test_validates_youtube_description_and_keyword_limits(self):
        with self.assertRaisesRegex(ValueError, "1,000 characters"):
            channel_branding.update_channel_branding(
                description="x" * 1001, confirm=True,
            )
        with self.assertRaisesRegex(ValueError, "500 characters"):
            channel_branding.update_channel_branding(
                keywords="keyword " * 80, confirm=True,
            )


if __name__ == "__main__":
    unittest.main()
