#!/usr/bin/env python3
"""Refresh GitHub's proxied image URL only when a hosted language card changes."""

from __future__ import annotations

import hashlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


README = Path("README.md")
API_HOST = "github-profile-summary-cards.vercel.app"
CARDS = {
    "repos-per-language": "Top Languages by Repo",
    "most-commit-language": "Top Languages by Commit",
}


def read_card(url: str, expected_title: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "image/svg+xml",
            "User-Agent": "OmSardar-profile-language-card-refresh/1.0",
        },
    )
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.status != 200:
                    raise RuntimeError(f"Card endpoint returned HTTP {response.status}")
                content_type = response.headers.get_content_type()
                if content_type != "image/svg+xml":
                    raise RuntimeError(f"Expected SVG, got {content_type}")
                body = response.read()
            root = ET.fromstring(body)
            if root.tag.rsplit("}", 1)[-1] != "svg":
                raise RuntimeError("Card response is not an SVG document")
            text = " ".join("".join(root.itertext()).split())
            if expected_title not in text:
                raise RuntimeError(f"Unexpected card response: {text[:160]}")
            return body
        except (urllib.error.URLError, TimeoutError, ET.ParseError, RuntimeError) as error:
            if attempt == 2:
                raise RuntimeError(f"Could not validate {expected_title}: {error}") from error
            time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


def with_content_version(source: str, card_route: str, title: str) -> str:
    parts = urllib.parse.urlsplit(source)
    if parts.netloc != API_HOST or f"/api/cards/{card_route}" != parts.path:
        raise RuntimeError(f"Unexpected source URL for {card_route}: {source}")

    params = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    api_params = [(key, value) for key, value in params if key != "v"]
    api_url = urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(api_params), "")
    )
    digest = hashlib.sha256(read_card(api_url, title)).hexdigest()[:16]
    versioned_params = [(key, value) for key, value in params if key != "v"]
    versioned_params.append(("v", digest))
    return urllib.parse.urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urllib.parse.urlencode(versioned_params),
            parts.fragment,
        )
    )


def main() -> int:
    readme = README.read_text(encoding="utf-8")
    changed = False
    for route, title in CARDS.items():
        pattern = re.compile(
            r'src="(?P<url>https://' + re.escape(API_HOST)
            + r"/api/cards/" + re.escape(route) + r"\?[^\"]+)\""
        )
        matches = list(pattern.finditer(readme))
        if len(matches) != 1:
            raise RuntimeError(f"Expected one README image URL for {route}; found {len(matches)}")
        old_url = matches[0].group("url")
        new_url = with_content_version(old_url, route, title)
        if new_url != old_url:
            readme = readme[: matches[0].start("url")] + new_url + readme[matches[0].end("url") :]
            print(f"Updated cache version for {route}")
            changed = True
        else:
            print(f"No card content change for {route}")

    if changed:
        README.write_text(readme, encoding="utf-8", newline="")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # Fail the workflow rather than publish an invalid/error card.
        print(f"::error::{error}", file=sys.stderr)
        sys.exit(1)
