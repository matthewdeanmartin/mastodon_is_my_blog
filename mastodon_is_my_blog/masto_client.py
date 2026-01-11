import os

import dotenv
from mastodon import Mastodon

from mastodon_is_my_blog.masto_client_timed import TimedMastodonClient

dotenv.load_dotenv()
PERF = True


def client(access_token: str | None = None) -> Mastodon | TimedMastodonClient:
    if PERF:
        # Not for production
        return TimedMastodonClient(
            access_token=access_token,
        )

    return Mastodon(
        api_base_url=os.environ["MASTODON_BASE_URL"].rstrip("/"),
        client_id=os.environ["MASTODON_CLIENT_ID"],
        client_secret=os.environ["MASTODON_CLIENT_SECRET"],
        access_token=access_token,
    )
