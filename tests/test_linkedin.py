import http.client
import unittest
import urllib.error
from unittest import mock

from jobhunt import linkedin


class _Resp:
    def __init__(self, body=b"ok", error=None):
        self.body, self.error = body, error

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        if self.error:
            raise self.error
        return self.body


def _client():
    return linkedin.Client(log=lambda *_: None, delay=(0, 0))


@mock.patch("jobhunt.linkedin.time.sleep", lambda *_: None)
class ClientRetries(unittest.TestCase):
    def test_retries_when_connection_drops_mid_download(self):
        # 2026-10-21: a reset while reading the body crashed the whole run.
        for error in (
            ConnectionResetError(54, "Connection reset by peer"),
            http.client.IncompleteRead(b"partial"),
            http.client.RemoteDisconnected("closed"),
        ):
            with self.subTest(error=type(error).__name__):
                replies = iter([_Resp(error=error), _Resp(b"<li>job</li>")])
                with mock.patch("urllib.request.urlopen", lambda *a, **k: next(replies)):
                    self.assertEqual(_client().get("https://example.test/"), "<li>job</li>")

    def test_gives_up_with_a_clear_message_when_offline(self):
        offline = urllib.error.URLError(OSError(8, "nodename nor servname provided"))

        def fail(*a, **k):
            raise offline

        with mock.patch("urllib.request.urlopen", fail):
            with self.assertRaises(linkedin.RateLimited) as caught:
                _client().get("https://example.test/")
        self.assertIn("network", str(caught.exception))
        self.assertNotIn("LinkedIn said", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
