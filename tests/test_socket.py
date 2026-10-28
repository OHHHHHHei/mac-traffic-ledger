import unittest
from unittest.mock import Mock, patch

from mac_traffic_ledger import ledger


class SocketTests(unittest.TestCase):
    def test_explicit_socket_does_not_fall_back(self):
        with patch.object(ledger, "SOCK", "/custom/mihomo.sock"):
            self.assertEqual(ledger.socket_paths(), ["/custom/mihomo.sock"])

    def test_default_includes_current_service_path(self):
        with patch.object(ledger, "SOCK", None):
            self.assertIn(
                f"/var/run/clash-verge-service/users/{ledger.os.getuid()}/verge-mihomo.sock",
                ledger.socket_paths(),
            )

    def test_missing_socket_falls_back_and_closes_failed_connection(self):
        missing, available = Mock(), Mock()
        missing.connect.side_effect = FileNotFoundError(2, "No such file")
        with (
            patch.object(ledger, "socket_paths", return_value=["/old", "/new"]),
            patch.object(ledger.socket, "socket", side_effect=[missing, available]),
        ):
            connection = ledger.UnixHTTP("localhost")
            connection.connect()
            self.assertIs(connection.sock, available)
            missing.close.assert_called_once()
            available.connect.assert_called_once_with("/new")
            connection.close()

    def test_unavailable_socket_reports_actionable_error(self):
        missing = Mock()
        missing.connect.side_effect = FileNotFoundError(2, "No such file")
        with (
            patch.object(ledger, "socket_paths", return_value=["/missing"]),
            patch.object(ledger.socket, "socket", return_value=missing),
        ):
            with self.assertRaisesRegex(ConnectionError, "Clash.*/missing"):
                ledger.UnixHTTP("localhost").connect()
            missing.close.assert_called_once()
