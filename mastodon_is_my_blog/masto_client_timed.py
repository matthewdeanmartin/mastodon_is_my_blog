import logging
import os
import time
from typing import Any

import dotenv
from mastodon import Mastodon

logger = logging.getLogger(__name__)

dotenv.load_dotenv()


class TimedMastodonClient:
    """Wrapper around Mastodon client with automatic timing"""

    def __init__(self, access_token: str | None = None):
        self.client: Mastodon = Mastodon(
            api_base_url=os.environ["MASTODON_BASE_URL"].rstrip("/"),
            client_id=os.environ["MASTODON_CLIENT_ID"],
            client_secret=os.environ["MASTODON_CLIENT_SECRET"],
            access_token=access_token,
        )
        self.logger: logging.Logger = logging.getLogger(__name__)

    def _timed_call(self, method_name: str, *args, **kwargs) -> Any:
        """Execute a Mastodon API call with timing"""
        start: float = time.perf_counter()
        self.logger.info(f"Mastodon API call: {method_name}")

        try:
            method = getattr(self.client, method_name)
            result = method(*args, **kwargs)
            elapsed: float = time.perf_counter() - start
            self.logger.info(f"Mastodon API completed: {method_name} in {elapsed:.3f}s")
            return result
        except Exception as e:
            elapsed: float = time.perf_counter() - start
            self.logger.error(
                f"Mastodon API failed: {method_name} after {elapsed:.3f}s - {str(e)}"
            )
            raise

    # Wrap common methods
    def account_verify_credentials(self):
        return self._timed_call("account_verify_credentials")

    def account_following(self, id: str, limit: int = 40):
        return self._timed_call("account_following", id, limit=limit)

    def account_followers(self, id: str, limit: int = 40):
        return self._timed_call("account_followers", id, limit=limit)

    def timeline_home(self, limit: int = 40):
        return self._timed_call("timeline_home", limit=limit)

    def account_statuses(self, id: str, limit: int = 40, **kwargs):
        return self._timed_call("account_statuses", id, limit=limit, **kwargs)

    def account_search(self, q: str, limit: int = 1):
        return self._timed_call("account_search", q, limit=limit)

    def account(self, id: str):
        return self._timed_call("account", id)

    def status(self, id: str):
        return self._timed_call("status", id)

    def status_context(self, id: str):
        return self._timed_call("status_context", id)

    def status_source(self, id: str):
        return self._timed_call("status_source", id)

    def status_post(self, status: str, **kwargs):
        return self._timed_call("status_post", status, **kwargs)

    def status_update(self, id: str, **kwargs):
        return self._timed_call("status_update", id, **kwargs)

    def auth_request_url(self, **kwargs):
        return self._timed_call("auth_request_url", **kwargs)

    def log_in(self, **kwargs):
        return self._timed_call("log_in", **kwargs)


def client(access_token: str | None = None) -> TimedMastodonClient:
    """Factory function for timed Mastodon client"""
    return TimedMastodonClient(access_token)
