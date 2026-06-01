"""
Maven Central registry client.

Fetches the latest stable release version for a given groupId:artifactId
from the standard Maven Central metadata endpoint.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import requests

MAVEN_CENTRAL = "https://repo1.maven.org/maven2"
TIMEOUT = 15


class MavenFetchError(Exception):
    pass


class MavenNotFoundError(MavenFetchError):
    """Raised when an artifact is not present on Maven Central (HTTP 404).

    This is not a hard error — it simply means the package lives on a private
    registry and cannot be checked for updates here.
    """


def _is_stable(version: str) -> bool:
    v = version.lower()
    return not any(x in v for x in ("snapshot", "-alpha", "-beta", ".alpha", ".beta", "-rc", "-m", ".m", "milestone"))


def fetch_latest_version(group_id: str, artifact_id: str) -> str:
    """Return the latest stable release version string from Maven Central."""
    group_path = group_id.replace(".", "/")
    url = f"{MAVEN_CENTRAL}/{group_path}/{artifact_id}/maven-metadata.xml"

    try:
        resp = requests.get(url, headers={"Accept": "application/xml"}, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise MavenFetchError(str(exc)) from exc

    if resp.status_code == 404:
        raise MavenNotFoundError(f"'{group_id}:{artifact_id}' not found on Maven Central.")
    if not resp.ok:
        raise MavenFetchError(f"Maven Central returned HTTP {resp.status_code}.")

    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError as exc:
        raise MavenFetchError("Invalid XML from Maven Central.") from exc

    versioning = root.find("versioning")
    if versioning is None:
        raise MavenFetchError("No <versioning> element found.")

    release = versioning.findtext("release") or versioning.findtext("latest") or ""

    if not release or not _is_stable(release):
        versions_el = versioning.find("versions")
        if versions_el is not None:
            stable = [
                v.text for v in versions_el.findall("version")
                if v.text and _is_stable(v.text)
            ]
            if stable:
                release = stable[-1]

    if not release:
        raise MavenFetchError("No stable release version found.")

    return release
