"""
Parser and writer for Maven pom.xml files.

Parsing uses xml.etree.ElementTree.
Writing uses targeted string replacement so comments and formatting survive.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Optional

from models.maven_dependency import MavenDependencyInfo

NS  = "http://maven.apache.org/POM/4.0.0"
_NS = f"{{{NS}}}"


def _tag(name: str) -> str:
    return f"{_NS}{name}"


def _text(el: ET.Element, name: str) -> Optional[str]:
    child = el.find(_tag(name))
    return (child.text or "").strip() or None if child is not None else None


def load(path: str) -> tuple[dict, list[MavenDependencyInfo]]:
    """Parse *path* and return (raw_info_dict, deps).

    raw_info_dict contains 'path' and 'project_name' keys for use by callers.
    """
    tree = ET.parse(path)
    root = tree.getroot()

    # Collect <properties> for version resolution
    props: dict[str, str] = {}
    props_el = root.find(_tag("properties"))
    if props_el is not None:
        for child in props_el:
            local = child.tag.replace(_NS, "")
            if child.text:
                props[local] = child.text.strip()

    deps: list[MavenDependencyInfo] = []
    deps_el = root.find(_tag("dependencies"))
    if deps_el is not None:
        for dep_el in deps_el.findall(_tag("dependency")):
            group_id    = _text(dep_el, "groupId") or ""
            artifact_id = _text(dep_el, "artifactId") or ""
            version_raw = _text(dep_el, "version")
            scope       = _text(dep_el, "scope") or "compile"
            optional    = _text(dep_el, "optional") == "true"

            if not group_id or not artifact_id:
                continue

            version: Optional[str] = None
            version_property: Optional[str] = None

            if version_raw:
                m = re.fullmatch(r"\$\{([^}]+)\}", version_raw)
                if m:
                    prop_name = m.group(1)
                    version_property = prop_name
                    version = props.get(prop_name)
                else:
                    version = version_raw

            deps.append(MavenDependencyInfo(
                group_id=group_id,
                artifact_id=artifact_id,
                version=version,
                version_property=version_property,
                scope=scope,
                optional=optional,
            ))

    artifact_id = _text(root, "artifactId") or ""
    name        = _text(root, "name") or artifact_id

    raw = {"path": path, "project_name": name}
    return raw, deps


def save(path: str, dep: MavenDependencyInfo, new_version: str) -> None:
    """Write *new_version* for *dep* into *path* using string replacement."""
    with open(path, encoding="utf-8") as fh:
        content = fh.read()

    if dep.version_property:
        prop = re.escape(dep.version_property)
        pattern = rf"(<{prop}>)[^<]*(</\s*{prop}>)"
        new_content = re.sub(pattern, rf"\g<1>{new_version}\g<2>", content)
    else:
        # Find the exact <dependency> block and replace its <version>
        dep_re = re.compile(r"(<dependency>[\s\S]*?</dependency>)", re.MULTILINE)
        def _replace(m: re.Match) -> str:
            block = m.group(1)
            if (f"<groupId>{dep.group_id}</groupId>" in block and
                    f"<artifactId>{dep.artifact_id}</artifactId>" in block):
                block = re.sub(
                    r"(<version>)[^<]*(</version>)",
                    rf"\g<1>{new_version}\g<2>",
                    block,
                )
            return block
        new_content = dep_re.sub(_replace, content)

    with open(path, "w", encoding="utf-8") as fh:
        fh.write(new_content)
