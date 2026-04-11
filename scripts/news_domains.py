#!/usr/bin/env python3
"""
Build a global top-1000 news-domain list.

This revised version is designed to be robust on low-tier or no API plans:
- Mediastack is optional and never required.
- Rate limits do not crash the whole run.
- Tranco is the main ranking backbone.
- A manual seed CSV is supported and recommended.
- Optional GDELT activity can be merged if available.
- Simple local caching is included for Mediastack requests.

Files:
- tranco.csv                      required, rank/domain CSV with rows like: 1,google.com
- seed_news_domains.csv          optional but recommended
- gdelt_domain_activity.csv      optional, columns: domain,gdelt_article_count_30d

Outputs:
- candidate_news_domains.csv
- top_1000_news_domains.csv
- review_queue.csv

Environment variables:
- MEDIASTACK_API_KEY             optional

Install:
    pip install requests pandas tldextract

Usage:
    python news_domains_revised.py
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import string
import time
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
import tldextract


MEDIASTACK_API_KEY = os.getenv("MEDIASTACK_API_KEY", "").strip()
TRANCO_CSV_PATH = "tranco.csv"
OPTIONAL_SEED_PATH = "seed_news_domains.csv"
OPTIONAL_GDELT_PATH = "gdelt_domain_activity.csv"

CACHE_DIR = Path(".cache_mediastack")
CACHE_DIR.mkdir(exist_ok=True)

# Conservative Mediastack settings for low-tier plans.
MEDIASTACK_ENABLED = bool(MEDIASTACK_API_KEY)
MEDIASTACK_SEARCH_TERMS = [
    "news",
    "times",
    "post",
    "guardian",
    "journal",
]
MEDIASTACK_PAGE_SIZE = 100
MEDIASTACK_SLEEP_SECONDS = 2.0
MEDIASTACK_MAX_RETRIES = 5
MEDIASTACK_MAX_PAGES_PER_SEARCH: Optional[int] = 1

DENYLIST = {
    "prnewswire.com",
    "businesswire.com",
    "globenewswire.com",
    "einnews.com",
    "accesswire.com",
    "medium.com",
    "substack.com",
    "blogspot.com",
    "wordpress.com",
}

BLOCKED_EXACT = {
    "facebook.com",
    "instagram.com",
    "x.com",
    "twitter.com",
    "youtube.com",
    "tiktok.com",
    "linkedin.com",
    "reddit.com",
}

BLOCKED_SUBSTRINGS = [
    "casino",
    "bet",
    "porn",
    "adult",
]

NEWS_KEYWORDS = [
    "news",
    "times",
    "post",
    "tribune",
    "herald",
    "daily",
    "chronicle",
    "guardian",
    "journal",
    "globe",
    "observer",
    "standard",
    "telegraph",
    "gazette",
    "express",
    "mirror",
]


def canonicalize_domain(url_or_domain: str) -> Optional[str]:
    if not url_or_domain:
        return None

    s = url_or_domain.strip().lower()
    s = re.sub(r"^https?://", "", s)
    s = s.split("/")[0]
    s = s.split("?")[0]
    s = s.split("#")[0]
    s = s.strip(".")

    if not s or "." not in s:
        return None

    ext = tldextract.extract(s)
    if not ext.domain or not ext.suffix:
        return None

    return f"{ext.domain}.{ext.suffix}"


def is_probably_news_domain(domain: str) -> bool:
    if not domain:
        return False

    if domain in DENYLIST or domain in BLOCKED_EXACT:
        return False

    for token in BLOCKED_SUBSTRINGS:
        if token in domain:
            return False

    return True


def looks_news_like(domain: str) -> bool:
    return any(keyword in domain for keyword in NEWS_KEYWORDS)


def source_quality_score(row: pd.Series) -> float:
    score = 0.35

    if pd.notna(row.get("country")) and str(row.get("country")).strip():
        score += 0.15

    if pd.notna(row.get("category")):
        cat = str(row["category"]).lower()
        if cat in {
            "general",
            "business",
            "technology",
            "sports",
            "health",
            "science",
            "entertainment",
        }:
            score += 0.20

    if pd.notna(row.get("source_origin")):
        origin = str(row["source_origin"]).lower()
        if origin == "seed":
            score += 0.25
        elif origin == "mediastack":
            score += 0.10
        elif origin == "tranco_heuristic":
            score += 0.05

    if pd.notna(row.get("outlet_name")) and len(str(row["outlet_name"]).strip()) > 2:
        score += 0.05

    return min(score, 1.0)


def normalized_tranco_score(rank: Optional[float]) -> float:
    if rank is None or pd.isna(rank):
        return 0.0

    rank = float(rank)
    if rank <= 0:
        return 0.0

    max_rank = 1_000_000
    clipped = min(rank, max_rank)
    return 1.0 - (math.log10(clipped) / math.log10(max_rank))


def get_json_with_backoff(url: str, params: dict, timeout: int = 30, max_retries: int = 5) -> dict:
    for attempt in range(max_retries):
        resp = requests.get(url, params=params, timeout=timeout)

        try:
            payload = resp.json()
        except Exception:
            payload = {"raw_text": resp.text}

        if resp.ok:
            return payload

        error_code = payload.get("error", {}).get("code") if isinstance(payload, dict) else None

        if resp.status_code == 429 or error_code == "rate_limit_reached":
            sleep_s = min(60, (2 ** attempt) + random.uniform(0.0, 1.0))
            print(f"Rate limited. Sleeping {sleep_s:.1f}s before retry...")
            time.sleep(sleep_s)
            continue

        raise RuntimeError(f"Mediastack request failed: {resp.status_code} {payload}")

    raise RuntimeError("Mediastack request failed after retries due to repeated rate limiting.")


def cached_get_json_with_backoff(url: str, params: dict, timeout: int = 30, max_retries: int = 5) -> dict:
    key = hashlib.sha256(
        json.dumps({"url": url, "params": params}, sort_keys=True).encode("utf-8")
    ).hexdigest()
    cache_file = CACHE_DIR / f"{key}.json"

    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))

    payload = get_json_with_backoff(url, params=params, timeout=timeout, max_retries=max_retries)
    cache_file.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def fetch_mediastack_sources(api_key: str) -> pd.DataFrame:
    if not api_key:
        return pd.DataFrame(columns=[
            "domain", "outlet_name", "country", "language",
            "category", "source_type", "source_origin"
        ])

    url = "http://api.mediastack.com/v1/sources"
    records: list[dict] = []

    for search_term in MEDIASTACK_SEARCH_TERMS:
        offset = 0
        page = 0

        while True:
            params = {
                "access_key": api_key,
                "search": search_term,
                "limit": MEDIASTACK_PAGE_SIZE,
                "offset": offset,
            }

            try:
                payload = cached_get_json_with_backoff(
                    url,
                    params=params,
                    timeout=30,
                    max_retries=MEDIASTACK_MAX_RETRIES,
                )
            except RuntimeError as e:
                message = str(e)
                if "rate_limit_reached" in message or "429" in message:
                    print("Warning: Mediastack rate limit reached. Stopping Mediastack fetch early.")
                    df = pd.DataFrame.from_records(records)
                    if df.empty:
                        return pd.DataFrame(columns=[
                            "domain", "outlet_name", "country", "language",
                            "category", "source_type", "source_origin"
                        ])
                    return df.drop_duplicates(subset=["domain"]).reset_index(drop=True)
                raise

            data = payload.get("data", [])
            if not data:
                break

            for item in data:
                domain = canonicalize_domain(item.get("url") or item.get("domain") or "")
                if not domain or not is_probably_news_domain(domain):
                    continue

                records.append({
                    "domain": domain,
                    "outlet_name": item.get("name"),
                    "country": item.get("country"),
                    "language": item.get("language"),
                    "category": item.get("category"),
                    "source_type": item.get("media_type"),
                    "source_origin": "mediastack",
                })

            if len(data) < MEDIASTACK_PAGE_SIZE:
                break

            offset += MEDIASTACK_PAGE_SIZE
            page += 1

            if MEDIASTACK_MAX_PAGES_PER_SEARCH is not None and page >= MEDIASTACK_MAX_PAGES_PER_SEARCH:
                break

            time.sleep(MEDIASTACK_SLEEP_SECONDS)

    df = pd.DataFrame.from_records(records)
    if df.empty:
        return pd.DataFrame(columns=[
            "domain", "outlet_name", "country", "language",
            "category", "source_type", "source_origin"
        ])

    return df.drop_duplicates(subset=["domain"]).reset_index(drop=True)


def load_seed_csv(path: str, source_origin: str = "seed") -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame(columns=[
            "domain", "outlet_name", "country", "language",
            "category", "source_type", "source_origin"
        ])

    df = pd.read_csv(path)
    if "domain" not in df.columns:
        raise ValueError(f"{path} must contain a 'domain' column")

    df["domain"] = df["domain"].map(canonicalize_domain)
    df = df[df["domain"].notna()].copy()

    for col in ["outlet_name", "country", "language", "category", "source_type"]:
        if col not in df.columns:
            df[col] = None

    df["source_origin"] = source_origin
    return df[[
        "domain", "outlet_name", "country", "language",
        "category", "source_type", "source_origin"
    ]]


def load_tranco_csv(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Missing {path}. Download a Tranco CSV and save it as {path}."
        )

    df = pd.read_csv(path, header=None, names=["tranco_rank", "domain"])
    df["domain"] = df["domain"].map(canonicalize_domain)
    df = df[df["domain"].notna()].copy()
    df["tranco_rank"] = pd.to_numeric(df["tranco_rank"], errors="coerce")
    return df.drop_duplicates(subset=["domain"])


def build_tranco_heuristic_candidates(tranco: pd.DataFrame, max_rank: int = 250_000) -> pd.DataFrame:
    """
    Build a fallback candidate universe from Tranco alone.
    This is intentionally heuristic: it catches likely news domains by domain name.
    The seed CSV is the recommended way to improve recall and precision.
    """
    subset = tranco[tranco["tranco_rank"] <= max_rank].copy()
    subset = subset[subset["domain"].map(is_probably_news_domain)]
    subset = subset[subset["domain"].map(looks_news_like)]

    subset["outlet_name"] = subset["domain"]
    subset["country"] = None
    subset["language"] = None
    subset["category"] = "general"
    subset["source_type"] = "unknown"
    subset["source_origin"] = "tranco_heuristic"

    return subset[[
        "domain", "outlet_name", "country", "language",
        "category", "source_type", "source_origin"
    ]].drop_duplicates(subset=["domain"])


def load_optional_gdelt(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame(columns=["domain", "gdelt_article_count_30d"])

    df = pd.read_csv(path)
    if "domain" not in df.columns or "gdelt_article_count_30d" not in df.columns:
        raise ValueError(
            f"{path} must have columns: domain, gdelt_article_count_30d"
        )

    df["domain"] = df["domain"].map(canonicalize_domain)
    df = df[df["domain"].notna()].copy()
    df["gdelt_article_count_30d"] = pd.to_numeric(df["gdelt_article_count_30d"], errors="coerce")
    return df.drop_duplicates(subset=["domain"])


def country_balance(df: pd.DataFrame, per_country_cap: int = 40) -> pd.DataFrame:
    if "country" not in df.columns:
        return df

    pieces = []
    for _, part in df.groupby(df["country"].fillna("__UNKNOWN__"), dropna=False):
        pieces.append(part.sort_values("final_score", ascending=False).head(per_country_cap))

    capped = pd.concat(pieces, ignore_index=True)
    return capped.sort_values("final_score", ascending=False).drop_duplicates(subset=["domain"])


def build_candidates(tranco: pd.DataFrame) -> pd.DataFrame:
    frames = []

    # Recommended: manual seed file.
    seed_df = load_seed_csv(OPTIONAL_SEED_PATH, source_origin="seed")
    if not seed_df.empty:
        frames.append(seed_df)
    else:
        print("Warning: seed_news_domains.csv not found. Recall will be weaker without it.")

    # Optional: Mediastack enrichment. Never required.
    if MEDIASTACK_ENABLED:
        try:
            mediastack_df = fetch_mediastack_sources(MEDIASTACK_API_KEY)
            if not mediastack_df.empty:
                frames.append(mediastack_df)
            else:
                print("Warning: Mediastack returned no sources or stopped early.")
        except Exception as e:
            print(f"Warning: Mediastack unavailable, continuing without it: {e}")
    else:
        print("Info: MEDIASTACK_API_KEY not set. Skipping Mediastack.")

    # Fallback: heuristic candidates from Tranco.
    heuristic_df = build_tranco_heuristic_candidates(tranco)
    if not heuristic_df.empty:
        frames.append(heuristic_df)

    if not frames:
        raise RuntimeError("No candidate domains found.")

    candidates = pd.concat(frames, ignore_index=True)
    candidates["domain"] = candidates["domain"].map(canonicalize_domain)
    candidates = candidates[candidates["domain"].notna()].copy()
    candidates = candidates[candidates["domain"].map(is_probably_news_domain)]

    # Prefer seed rows over other sources where duplicates exist.
    priority = {"seed": 0, "mediastack": 1, "tranco_heuristic": 2}
    candidates["_priority"] = candidates["source_origin"].map(lambda x: priority.get(str(x).lower(), 99))

    candidates = (
        candidates
        .sort_values(by=["_priority", "outlet_name", "country"], na_position="last")
        .drop_duplicates(subset=["domain"], keep="first")
        .drop(columns=["_priority"])
        .reset_index(drop=True)
    )

    return candidates


def main() -> None:
    tranco = load_tranco_csv(TRANCO_CSV_PATH)
    gdelt = load_optional_gdelt(OPTIONAL_GDELT_PATH)
    candidates = build_candidates(tranco)

    df = candidates.merge(tranco, on="domain", how="left")
    df = df.merge(gdelt, on="domain", how="left")

    df["source_quality_score"] = df.apply(source_quality_score, axis=1)
    df["tranco_score"] = df["tranco_rank"].map(normalized_tranco_score)

    if "gdelt_article_count_30d" in df.columns and df["gdelt_article_count_30d"].notna().any():
        max_count = df["gdelt_article_count_30d"].max()
        if pd.isna(max_count) or max_count <= 0:
            df["gdelt_score"] = 0.0
        else:
            df["gdelt_score"] = (
                df["gdelt_article_count_30d"].fillna(0).map(lambda x: math.log1p(x))
                / math.log1p(max_count)
            )
        df["final_score"] = (
            0.60 * df["tranco_score"] +
            0.25 * df["gdelt_score"] +
            0.15 * df["source_quality_score"]
        )
    else:
        df["gdelt_score"] = 0.0
        df["final_score"] = (
            0.75 * df["tranco_score"] +
            0.25 * df["source_quality_score"]
        )

    review_queue = df[df["tranco_rank"].isna()].copy()
    balanced = country_balance(df, per_country_cap=40)

    top_1000 = (
        balanced
        .sort_values(["final_score", "tranco_rank"], ascending=[False, True], na_position="last")
        .drop_duplicates(subset=["domain"])
        .head(1000)
        .reset_index(drop=True)
    )

    candidate_cols = [
        "domain",
        "outlet_name",
        "country",
        "language",
        "category",
        "source_type",
        "source_origin",
        "tranco_rank",
        "tranco_score",
        "gdelt_article_count_30d",
        "gdelt_score",
        "source_quality_score",
        "final_score",
    ]
    candidate_cols = [c for c in candidate_cols if c in df.columns]

    df.sort_values("final_score", ascending=False).to_csv(
        "candidate_news_domains.csv", index=False, columns=candidate_cols
    )
    top_1000.to_csv(
        "top_1000_news_domains.csv", index=False, columns=candidate_cols
    )
    review_queue.sort_values(["country", "outlet_name"], na_position="last").to_csv(
        "review_queue.csv", index=False, columns=candidate_cols
    )

    print("Wrote:")
    print("  candidate_news_domains.csv")
    print("  top_1000_news_domains.csv")
    print("  review_queue.csv")


if __name__ == "__main__":
    main()
