import importlib
import unittest
from datetime import timezone
from pathlib import Path
from unittest.mock import patch

import plugins
import requests


class TestGrizzlySmsTimeParsing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        plugins.instance.current_plugin_path = str(root / "plugins" / "grizzly_sms")
        importlib.import_module("plugins.grizzly_sms")
        cls.plugin_class = plugins.instance.plugins["GRIZZLYSMS"]

    def setUp(self):
        self.plugin = self.plugin_class()
        self.plugin.config["activation_time_zone"] = "UTC"
        self.plugin.config["display_time_zone"] = "+08:00"

    def test_naive_activation_end_is_treated_as_utc(self):
        parsed = self.plugin._parse_activation_time("2026-05-07 14:18:16")

        self.assertEqual(parsed.tzinfo, timezone.utc)
        self.assertEqual(parsed.isoformat(), "2026-05-07T14:18:16+00:00")

    def test_iso_activation_end_with_z_is_supported(self):
        parsed = self.plugin._parse_activation_time("2026-05-07T14:18:16Z")

        self.assertEqual(parsed.tzinfo, timezone.utc)
        self.assertEqual(parsed.isoformat(), "2026-05-07T14:18:16+00:00")

    def test_iso_activation_end_with_offset_is_normalized_to_utc(self):
        parsed = self.plugin._parse_activation_time("2026-05-07T22:18:16+08:00")

        self.assertEqual(parsed.tzinfo, timezone.utc)
        self.assertEqual(parsed.isoformat(), "2026-05-07T14:18:16+00:00")

    def test_time_is_formatted_in_user_display_timezone(self):
        formatted = self.plugin._format_api_time("2026-05-07 14:18:16")

        self.assertEqual(formatted, "2026-05-07 22:18:16 (UTC+08:00)")

    def test_number_response_formats_all_activation_times(self):
        text = self.plugin._format_number(
            {
                "phoneNumber": "18036181752",
                "activationId": 495357953,
                "activationCost": 0.35,
                "currency": 643,
                "countryCode": "12",
                "activationTime": "2026-05-07 13:58:16",
                "activationCancel": "2026-05-07 14:03:16",
                "activationEnd": "2026-05-07 14:18:16",
                "canGetAnotherSms": "0",
            }
        )

        self.assertIn("开始时间：2026-05-07 21:58:16 (UTC+08:00)", text)
        self.assertIn("取消截止：2026-05-07 22:03:16 (UTC+08:00)", text)
        self.assertIn("激活截止：2026-05-07 22:18:16 (UTC+08:00)", text)

    def test_sms_response_formats_received_time(self):
        text = self.plugin._format_sms(
            "495357953",
            {
                "sms": {
                    "dateTime": "2026-02-26 12:05:55",
                    "code": "852508",
                    "text": "852508",
                }
            },
        )

        self.assertIn("接收时间：2026-02-26 20:05:55 (UTC+08:00)", text)

    def test_debug_polling_is_disabled_by_default(self):
        self.plugin.config.pop("debug_polling", None)

        self.assertFalse(self.plugin._debug_polling_enabled())

    def test_debug_polling_logs_poll_status_when_enabled(self):
        self.plugin.config["debug_polling"] = True

        with patch("plugins.grizzly_sms.grizzly_sms.logger.info") as mock_info:
            self.plugin._log_get_status_poll("495357953", True, {"sms": {}}, "")

        mock_info.assert_called_once()
        self.assertIn("poll getStatusV2 activation_id=%s", mock_info.call_args.args[0])
        self.assertEqual(mock_info.call_args.args[1], "495357953")

    def test_polling_fetches_sms_only_after_access_ready(self):
        with patch.object(self.plugin, "_set_activation_status", return_value=(True, "ACCESS_READY", "")) as mock_set:
            with patch.object(self.plugin, "_get_status", return_value=(True, {"sms": {"code": "852508"}}, "")) as mock_get:
                with patch.object(self.plugin, "_notify") as mock_notify:
                    with patch("plugins.grizzly_sms.grizzly_sms.time.sleep"):
                        self.plugin._poll_status({}, "495357953", "2099-05-07 14:18:16")

        mock_set.assert_called_once_with("495357953", 1)
        mock_get.assert_called_once_with("495357953")
        mock_notify.assert_called_once()

    def test_polling_stops_when_set_status_returns_other_business_state(self):
        with patch.object(self.plugin, "_set_activation_status", return_value=(True, "ACCESS_CANCEL", "")):
            with patch.object(self.plugin, "_get_status") as mock_get:
                with patch.object(self.plugin, "_notify") as mock_notify:
                    with patch("plugins.grizzly_sms.grizzly_sms.time.sleep"):
                        self.plugin._poll_status({}, "495357953", "2099-05-07 14:18:16")

        mock_get.assert_not_called()
        mock_notify.assert_called_once()
        self.assertIn("激活已取消", mock_notify.call_args.args[1])

    def test_connection_reset_error_is_reported_with_set_status_context(self):
        error = requests.ConnectionError("Connection aborted.", ConnectionResetError(54, "Connection reset by peer"))

        with patch.object(self.plugin, "_set_activation_status", return_value=(False, "", self.plugin._format_request_exception(error))):
            with patch.object(self.plugin, "_get_status") as mock_get:
                with patch.object(self.plugin, "_notify") as mock_notify:
                    with patch("plugins.grizzly_sms.grizzly_sms.time.sleep"):
                        self.plugin._poll_status({}, "508287940", "2099-05-07 14:18:16")

        mock_get.assert_not_called()
        mock_notify.assert_called_once()
        message = mock_notify.call_args.args[1]
        self.assertIn("setStatus 请求失败", message)
        self.assertIn("连接被对端重置", message)


if __name__ == "__main__":
    unittest.main()
