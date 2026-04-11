import logging
import time
from typing import Any

import dotenv
from mastodon import Mastodon

logger = logging.getLogger(__name__)

dotenv.load_dotenv()


class TimedMastodonClient:
    """Wrapper around Mastodon client with automatic timing"""

    def __init__(
        self,
        api_base_url: str,
        client_id: str,
        client_secret: str,
        access_token: str | None = None,
    ):
        self.client: Mastodon = Mastodon(
            api_base_url=api_base_url,
            client_id=client_id,
            client_secret=client_secret,
            access_token=access_token,
        )
        self.logger: logging.Logger = logging.getLogger(__name__)

    def _timed_call(self, method_name: str, *args, **kwargs) -> Any:
        """Execute a Mastodon API call with timing"""
        start: float = time.perf_counter()
        self.logger.info("Mastodon API call: %s", method_name)

        try:
            method = getattr(self.client, method_name)
            result = method(*args, **kwargs)
            elapsed: float = time.perf_counter() - start
            self.logger.info("Mastodon API completed: %s in %.3fs", method_name, elapsed)
            return result
        except Exception as e:
            elapsed = time.perf_counter() - start
            self.logger.error(
                "Mastodon API failed: %s after %.3fs - %s", method_name, elapsed, e
            )
            raise

    # Wrap common methods
    def account_verify_credentials(self):
        return self._timed_call("account_verify_credentials")

    def account_following(self, account_id: str, limit: int = 40):
        return self._timed_call("account_following", account_id, limit=limit)

    def account_followers(self, account_id: str, limit: int = 40):
        return self._timed_call("account_followers", account_id, limit=limit)

    def timeline_home(self, limit: int = 40):
        return self._timed_call("timeline_home", limit=limit)

    def account_statuses(self, account_id: str, limit: int = 40, **kwargs):
        return self._timed_call("account_statuses", account_id, limit=limit, **kwargs)

    def account_search(self, q: str, limit: int = 1):
        return self._timed_call("account_search", q, limit=limit)

    def account(self, account_id: str):
        return self._timed_call("account", account_id)

    def status(self, status_id: str):
        return self._timed_call("status", status_id)

    def status_context(self, status_id: str):
        return self._timed_call("status_context", status_id)

    def status_source(self, status_id: str):
        return self._timed_call("status_source", status_id)

    def status_post(self, status: str, **kwargs):
        return self._timed_call("status_post", status, **kwargs)

    def status_update(self, status_id: str, **kwargs):
        return self._timed_call("status_update", status_id, **kwargs)

    def auth_request_url(self, **kwargs):
        return self._timed_call("auth_request_url", **kwargs)

    def log_in(self, **kwargs):
        return self._timed_call("log_in", **kwargs)

    def notifications(self, limit: int = 40, **kwargs):
        return self._timed_call("notifications", limit=limit, **kwargs)
