# Well-known Mastodon / ActivityPub instance domains.
# Used to detect whether a link points to a fediverse post (not an external web link).
# This covers ~80% of real-world traffic. The URL path pattern /@user/id is also checked
# as a fallback for instances not listed here.

MASTODON_INSTANCES: frozenset[str] = frozenset(
    {
        # Top-tier general instances
        "mastodon.social",
        "mastodon.online",
        "mastodon.world",
        "mastodon.cloud",
        "mastodon.xyz",
        "mastodon.lol",
        "mastodon.sdf.org",
        "mastodon.technology",
        "mastodon.gamedev.place",
        "mastodon.art",
        "mastodon.education",
        "mastodon.ie",
        "mastodon.scot",
        "mastodon.nz",
        "mastodon.au",
        "mastodon.green",
        # infosec / tech
        "infosec.exchange",
        "hachyderm.io",
        "fosstodon.org",
        "techhub.social",
        "sigmoid.social",
        "aus.social",
        "social.coop",
        "toot.cafe",
        "chaos.social",
        "social.heise.de",
        "botsin.space",
        "programmer.social",
        "ioc.exchange",
        # science / academia
        "scholar.social",
        "scicomm.xyz",
        "fediscience.org",
        "hcommons.social",
        "sciences.social",
        "akademienl.social",
        "mathstodon.xyz",
        "genomic.social",
        # journalism / media
        "journalism.social",
        "newsie.social",
        # arts / creative
        "photog.social",
        "pixelfed.social",
        "wandering.shop",
        "tabletop.social",
        "dice.camp",
        "assemblag.es",
        # LGBTQ+ / community
        "lgbt.io",
        "queer.party",
        "tech.lgbt",
        # regional / language
        "social.cologne",
        "nrw.social",
        "bonn.social",
        "muenchen.social",
        "ruhr.social",
        "bawü.social",
        "norden.social",
        "sueden.social",
        "mstdn.social",
        "mstdn.jp",
        "pawoo.net",
        "fedibird.com",
        "vivaldi.net",
        "tooting.at",
        "social.vivaldi.net",
        # Smaller well-known instances
        "toot.community",
        "kolektiva.social",
        "universeodon.com",
        "indieweb.social",
        "sfba.social",
        "octodon.social",
        "social.lol",
        "social.network.europa.eu",
        "home.social",
        "flipboard.com",  # runs ActivityPub
        "threads.net",  # Meta ActivityPub
        "bsky.brid.gy",  # Bluesky bridge
    }
)


def is_mastodon_domain(domain: str) -> bool:
    """Return True if domain is a known Mastodon/fediverse instance."""
    clean = domain.lower().removeprefix("www.")
    return clean in MASTODON_INSTANCES
