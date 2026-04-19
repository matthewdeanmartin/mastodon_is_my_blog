import os
import re


def fix_file(path, func):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        content = f.read()
    new_content = func(content)
    if new_content != content:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)


def generic_cleanup(content):
    content = content.replace("== True", "is True")
    content = content.replace("== False", "is False")
    content = content.replace("== None", "is None")
    content = content.replace("!= None", "is not None")
    # Lazy logging for common patterns
    content = re.sub(
        r'logger\.info\(f"([^"]+)\{([^}]+)\}([^"]*)"\)',
        r'logger.info("\1%s\3", \2)',
        content,
    )
    content = re.sub(
        r'logger\.error\(f"([^"]+)\{([^}]+)\}([^"]*)"\)',
        r'logger.error("\1%s\3", \2)',
        content,
    )
    content = re.sub(
        r'logger\.warning\(f"([^"]+)\{([^}]+)\}([^"]*)"\)',
        r'logger.warning("\1%s\3", \2)',
        content,
    )
    content = re.sub(
        r'logger\.debug\(f"([^"]+)\{([^}]+)\}([^"]*)"\)',
        r'logger.debug("\1%s\3", \2)',
        content,
    )
    return content


def fix_store(content):
    if "from __future__ import annotations" not in content:
        content = "from __future__ import annotations\n" + content
    return generic_cleanup(content)


def fix_main(content):
    content = content.replace(
        "async def lifespan(app: FastAPI):", "async def lifespan(_: FastAPI):"
    )
    return generic_cleanup(content)


def fix_accounts(content):
    content = content.replace("my_account_id = ", "_ = ")
    content = content.replace("except:", "except Exception:")
    return generic_cleanup(content)


def fix_admin(content):
    return generic_cleanup(content)


def fix_masto_client_timed(content):
    content = content.replace("(self, id: str", "(self, account_id: str")
    content = content.replace(
        "def account_following(self, id: str",
        "def account_following(self, account_id: str",
    )
    content = content.replace(
        'account_following", id,', 'account_following", account_id,'
    )
    content = content.replace(
        "def account_followers(self, id: str",
        "def account_followers(self, account_id: str",
    )
    content = content.replace(
        'account_followers", id,', 'account_followers", account_id,'
    )
    content = content.replace(
        "def account_statuses(self, id: str",
        "def account_statuses(self, account_id: str",
    )
    content = content.replace(
        'account_statuses", id,', 'account_statuses", account_id,'
    )
    content = content.replace(
        "def account(self, id: str):", "def account(self, account_id: str):"
    )
    content = content.replace('account", id)', 'account", account_id)')
    content = content.replace(
        "def status(self, id: str):", "def status(self, status_id: str):"
    )
    content = content.replace('status", id)', 'status", status_id)')
    content = content.replace(
        "def status_context(self, id: str):",
        "def status_context(self, status_id: str):",
    )
    content = content.replace('status_context", id)', 'status_context", status_id)')
    content = content.replace(
        "def status_source(self, id: str):", "def status_source(self, status_id: str):"
    )
    content = content.replace('status_source", id)', 'status_source", status_id)')
    content = content.replace(
        "def status_update(self, id: str", "def status_update(self, status_id: str"
    )
    content = content.replace('status_update", id,', 'status_update", status_id,')
    return generic_cleanup(content)


def fix_masto_client(content):
    if "import os" not in content:
        content = content.replace("import logging", "import logging\nimport os")
    content = re.sub(
        r"def client\(\s*\*,[^)]+access_token: str,\s*\)\s*->",
        r'def client(\n    *,\n    base_url: str = os.environ.get("MASTODON_API_BASE_URL", ""),\n    client_id: str = os.environ.get("MASTODON_CLIENT_ID", ""),\n    client_secret: str = os.environ.get("MASTODON_CLIENT_SECRET", ""),\n    access_token: str = os.environ.get("MASTODON_ACCESS_TOKEN", ""),\n) ->',
        content,
        flags=re.MULTILINE,
    )
    return generic_cleanup(content)


def fix_inspect_post(content):
    if "import logging" not in content:
        content = "import logging\n" + content
    if "logger =" not in content:
        content = content.replace(
            "DOMAIN_CONFIG", "DOMAIN_CONFIG\n\nlogger = logging.getLogger(__name__)"
        )
    content = re.sub(
        r"except Exception:\s*logger\.error\(e\)\s*continue",
        r'except Exception as e:\n            logger.error("Error analyzing content: %s", e)\n            continue',
        content,
        flags=re.MULTILINE,
    )
    return generic_cleanup(content)


def fix_identity_verifier(content):
    content = content.replace("except Exception:", "except Exception as e:")
    content = content.replace(
        "logger.error(e)", 'logger.error("Identity verification failed: %s", e)'
    )
    return generic_cleanup(content)


def fix_queries(content):
    return generic_cleanup(content)


def fix_notification_sync(content):
    return generic_cleanup(content)


def fix_routes_posts(content):
    content = content.replace(
        "async def get_post_context(id: str,",
        "async def get_post_context(post_id: str,",
    )
    content = content.replace("status_id=id", "status_id=post_id")
    return generic_cleanup(content)


if __name__ == "__main__":
    fix_file("../mastodon_is_my_blog/store.py", fix_store)
    fix_file("../mastodon_is_my_blog/main.py", fix_main)
    fix_file("../mastodon_is_my_blog/routes/accounts.py", fix_accounts)
    fix_file("../mastodon_is_my_blog/routes/admin.py", fix_admin)
    fix_file(
        "../mastodon_is_my_blog/mastodon_apis/masto_client_timed.py",
        fix_masto_client_timed,
    )
    fix_file("../mastodon_is_my_blog/mastodon_apis/masto_client.py", fix_masto_client)
    fix_file("../mastodon_is_my_blog/inspect_post.py", fix_inspect_post)
    fix_file("../mastodon_is_my_blog/identity_verifier.py", fix_identity_verifier)
    fix_file("../mastodon_is_my_blog/queries.py", fix_queries)
    fix_file("../mastodon_is_my_blog/notification_sync.py", fix_notification_sync)
    fix_file("../mastodon_is_my_blog/routes/posts.py", fix_routes_posts)
