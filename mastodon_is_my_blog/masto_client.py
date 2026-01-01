import os
from mastodon import Mastodon

def client(access_token: str | None = None) -> Mastodon:
    return Mastodon(
        api_base_url=os.environ["MASTODON_BASE_URL"].rstrip("/"),
        client_id=os.environ["MASTODON_CLIENT_ID"],
        client_secret=os.environ["MASTODON_CLIENT_SECRET"],
        access_token=access_token,
    )
