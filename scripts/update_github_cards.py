#!/usr/bin/env python3
"""Fetch public GitHub data and render the profile's SVG analytics cards."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Iterable


API_URL = "https://api.github.com"
CARD_WIDTH = 600
CARD_HEIGHT = 380
BAR_COLORS = ("#38BDF8", "#60A5FA", "#A5F3FC", "#334155")


class GitHubAPIError(RuntimeError):
    """A concise, user-facing GitHub API error."""


class GitHubClient:
    def __init__(self, token: str | None = None) -> None:
        self.token = token

    def get(self, path: str, params: dict[str, str] | None = None) -> Any:
        url = f"{API_URL}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"

        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "arlequin-stack-profile-cards",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            try:
                message = json.loads(detail).get("message", detail)
            except json.JSONDecodeError:
                message = detail
            raise GitHubAPIError(f"GitHub API returned {error.code} for {path}: {message}") from error
        except urllib.error.URLError as error:
            raise GitHubAPIError(f"Could not reach GitHub API for {path}: {error.reason}") from error

    def get_paginated(self, path: str, params: dict[str, str] | None = None) -> list[Any]:
        items: list[Any] = []
        page = 1
        while True:
            page_params = dict(params or {})
            page_params.update({"per_page": "100", "page": str(page)})
            batch = self.get(path, page_params)
            if not isinstance(batch, list):
                raise GitHubAPIError(f"Expected a list from {path}, received {type(batch).__name__}")
            items.extend(batch)
            if len(batch) < 100:
                return items
            page += 1


@dataclass(frozen=True)
class ProfileData:
    username: str
    commits: int
    stars: int
    pull_requests: int
    repositories: int
    languages: dict[str, int]
    updated_at: datetime


def fetch_profile_data(client: GitHubClient, username: str) -> ProfileData:
    encoded_username = urllib.parse.quote(username, safe="")
    user = client.get(f"/users/{encoded_username}")
    repos = client.get_paginated(
        f"/users/{encoded_username}/repos",
        {"type": "owner", "sort": "updated", "direction": "desc"},
    )

    language_bytes: defaultdict[str, int] = defaultdict(int)
    stars = 0
    for repo in repos:
        stars += int(repo.get("stargazers_count", 0))
        if repo.get("fork") or repo.get("archived"):
            continue
        owner = urllib.parse.quote(repo["owner"]["login"], safe="")
        name = urllib.parse.quote(repo["name"], safe="")
        for language, byte_count in client.get(f"/repos/{owner}/{name}/languages").items():
            language_bytes[language] += int(byte_count)

    commits = client.get("/search/commits", {"q": f"author:{username}"})
    pull_requests = client.get("/search/issues", {"q": f"type:pr author:{username}"})

    return ProfileData(
        username=username,
        commits=int(commits.get("total_count", 0)),
        stars=stars,
        pull_requests=int(pull_requests.get("total_count", 0)),
        repositories=int(user.get("public_repos", len(repos))),
        languages=dict(language_bytes),
        updated_at=datetime.now(timezone.utc),
    )


def load_fixture(path: Path, username: str) -> ProfileData:
    payload = json.loads(path.read_text(encoding="utf-8"))
    language_bytes: defaultdict[str, int] = defaultdict(int)
    stars = 0
    repos = payload.get("repos", [])
    for repo in repos:
        stars += int(repo.get("stargazers_count", 0))
        if repo.get("fork") or repo.get("archived"):
            continue
        for language, byte_count in repo.get("languages", {}).items():
            language_bytes[language] += int(byte_count)

    raw_updated_at = payload.get("updated_at")
    updated_at = (
        datetime.fromisoformat(raw_updated_at.replace("Z", "+00:00"))
        if raw_updated_at
        else datetime.now(timezone.utc)
    )
    return ProfileData(
        username=username,
        commits=int(payload.get("commits_total", 0)),
        stars=stars,
        pull_requests=int(payload.get("pull_requests_total", 0)),
        repositories=int(payload.get("user", {}).get("public_repos", len(repos))),
        languages=dict(language_bytes),
        updated_at=updated_at,
    )


def language_breakdown(languages: dict[str, int]) -> list[tuple[str, float]]:
    positive = [(name, count) for name, count in languages.items() if count > 0]
    ordered = sorted(positive, key=lambda item: (-item[1], item[0].lower()))
    total = sum(count for _, count in ordered)
    if not total:
        return []

    if len(ordered) > 4:
        shown = ordered[:3]
        shown.append(("Other", sum(count for _, count in ordered[3:])))
    else:
        shown = ordered
    return [(name, count * 100 / total) for name, count in shown]


def format_number(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M".replace(".0M", "M")
    if value >= 1_000:
        return f"{value / 1_000:.1f}K".replace(".0K", "K")
    return str(value)


def svg_shell(title: str, eyebrow: str, subtitle: str, description: str, body: str, updated_at: datetime) -> str:
    updated = updated_at.astimezone(timezone.utc).strftime("%Y-%m-%d UTC")
    safe_title = escape(title)
    safe_description = escape(description)
    return f'''<svg width="{CARD_WIDTH}" height="{CARD_HEIGHT}" viewBox="0 0 {CARD_WIDTH} {CARD_HEIGHT}" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title desc">
  <title id="title">{safe_title}</title>
  <desc id="desc">{safe_description}</desc>
  <defs>
    <linearGradient id="bg" x1="24" y1="16" x2="576" y2="364" gradientUnits="userSpaceOnUse">
      <stop stop-color="#111827"/><stop offset="0.52" stop-color="#080D15"/><stop offset="1" stop-color="#03060B"/>
    </linearGradient>
    <linearGradient id="accent" x1="44" y1="0" x2="556" y2="0" gradientUnits="userSpaceOnUse">
      <stop stop-color="#38BDF8"/><stop offset="0.55" stop-color="#60A5FA"/><stop offset="1" stop-color="#2563EB"/>
    </linearGradient>
    <radialGradient id="glow" cx="0" cy="0" r="1" gradientTransform="translate(535 40) rotate(135) scale(210 245)" gradientUnits="userSpaceOnUse">
      <stop stop-color="#0EA5E9" stop-opacity=".18"/><stop offset="1" stop-color="#0EA5E9" stop-opacity="0"/>
    </radialGradient>
    <filter id="dotGlow" x="-300%" y="-300%" width="700%" height="700%"><feGaussianBlur stdDeviation="2.5" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  </defs>
  <rect x="1" y="1" width="598" height="378" rx="24" fill="url(#bg)"/>
  <rect x="1" y="1" width="598" height="378" rx="24" fill="url(#glow)"/>
  <rect x="1.75" y="1.75" width="596.5" height="376.5" rx="23.25" stroke="#FFFFFF" stroke-opacity=".12" stroke-width="1.5"/>
  <circle cx="45" cy="43" r="5" fill="#38BDF8" filter="url(#dotGlow)"/>
  <text x="61" y="47" fill="#94A3B8" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="11" font-weight="700" letter-spacing="2.1">{escape(eyebrow)}</text>
  <text x="44" y="91" fill="#F8FAFC" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="29" font-weight="700" letter-spacing="-.7">{safe_title}</text>
  <text x="556" y="88" fill="#64748B" text-anchor="end" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="10" font-weight="700" letter-spacing="1.4">{escape(subtitle)}</text>
  <rect x="44" y="108" width="512" height="1.5" rx=".75" fill="url(#accent)" opacity=".78"/>
  {body}
  <text x="44" y="350" fill="#64748B" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="10" font-weight="600" letter-spacing="1.1">LIVE PUBLIC DATA</text>
  <text x="556" y="350" fill="#64748B" text-anchor="end" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="10" font-weight="600" letter-spacing="1.1">UPDATED {updated}</text>
</svg>
'''


def render_statistics(data: ProfileData) -> str:
    rows = (
        ("COMMITS", data.commits, "PUBLIC AUTHOR MATCHES"),
        ("STARS", data.stars, "ON OWNED REPOSITORIES"),
        ("PULL REQUESTS", data.pull_requests, "PUBLIC PRS CREATED"),
        ("REPOSITORIES", data.repositories, "PUBLIC REPOSITORIES"),
    )
    parts = ['<g font-family="Inter,Segoe UI,Arial,sans-serif">']
    for index, (label, value, note) in enumerate(rows):
        y = 148 + index * 46
        parts.append(f'''<text x="44" y="{y}" fill="#E2E8F0" font-size="13" font-weight="700" letter-spacing=".8">{escape(label)}</text>
    <text x="44" y="{y + 16}" fill="#64748B" font-size="9" font-weight="600" letter-spacing=".8">{escape(note)}</text>
    <text x="556" y="{y + 9}" fill="#F8FAFC" text-anchor="end" font-size="24" font-weight="750">{format_number(value)}</text>''')
        if index < len(rows) - 1:
            parts.append(f'<rect x="44" y="{y + 28}" width="512" height="1" fill="#FFFFFF" opacity=".07"/>')
    parts.append("</g>")
    description = (
        f"Public GitHub statistics for {data.username}: {data.commits} commits, {data.stars} stars, "
        f"{data.pull_requests} pull requests, and {data.repositories} repositories."
    )
    return svg_shell("Statistics", "ARLEQUIN-STACK / PROFILE", "GITHUB OVERVIEW", description, "\n  ".join(parts), data.updated_at)


def render_languages(data: ProfileData) -> str:
    breakdown = language_breakdown(data.languages)
    rows = breakdown or [("No public code", 0.0)]
    rows = rows[:4]
    while len(rows) < 4:
        rows.append(("—", 0.0))

    parts = ['<g font-family="Inter,Segoe UI,Arial,sans-serif">']
    for index, (name, percentage) in enumerate(rows):
        y = 143 + index * 46
        color = BAR_COLORS[index]
        parts.append(f'''<circle cx="49" cy="{y - 1}" r="4" fill="{color}"/>
    <text x="62" y="{y + 4}" fill="#E2E8F0" font-size="13" font-weight="700">{escape(name)}</text>
    <text x="556" y="{y + 4}" fill="#F8FAFC" text-anchor="end" font-size="16" font-weight="750">{percentage:.1f}%</text>
    <rect x="62" y="{y + 15}" width="494" height="4" rx="2" fill="#1E293B"/>
    <rect x="62" y="{y + 15}" width="{494 * percentage / 100:.2f}" height="4" rx="2" fill="{color}"/>''')
    parts.append("</g>")

    description_items = ", ".join(f"{name} {percentage:.1f}%" for name, percentage in breakdown)
    description = f"Language distribution across public non-fork repositories for {data.username}: {description_items or 'no language data'}."
    return svg_shell("Languages", "ARLEQUIN-STACK / PROFILE", "CODE DISTRIBUTION", description, "\n  ".join(parts), data.updated_at)


def write_cards(data: ProfileData, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "statistics.svg").write_text(render_statistics(data), encoding="utf-8")
    (output_dir / "languages.svg").write_text(render_languages(data), encoding="utf-8")


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", default="arlequin-stack")
    parser.add_argument("--output-dir", type=Path, default=Path("assets"))
    parser.add_argument("--fixture", type=Path, help="Use local fixture data instead of the GitHub API")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.fixture:
            data = load_fixture(args.fixture, args.username)
        else:
            token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
            data = fetch_profile_data(GitHubClient(token), args.username)
        write_cards(data, args.output_dir)
    except (GitHubAPIError, KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"Updated {args.output_dir / 'statistics.svg'} and {args.output_dir / 'languages.svg'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
