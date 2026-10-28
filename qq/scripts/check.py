#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""qq plugin attached audit: territory, declaration and leakage checks (read-only).

Semantic items (whether a group answer actually stayed inside the public subset)
remain under the check command; this script only checks the mechanical surfaces.
"""
import json
import re

POLICY = "qq/policy.md"

SECRET_PATTERNS = [
    re.compile(r"(?i)client[_-]?secret\s*[:=]\s*\S+"),
    re.compile(r"(?i)access[_-]?token\s*[:=]\s*\S+"),
    re.compile(r"(?i)(user|group|member)_openid\s*[:=]\s*\S+"),
    re.compile(r"\b[0-9a-fA-F]{32,}\b"),
]


def check(ctx):
    issues = []
    policy = None
    for rel, fm, body in ctx.pages:
        ptype = fm.get("type")

        if ptype == "qq" and not rel.startswith("qq/"):
            issues.append({"level": "error", "message": f"{rel}: type: qq page outside wiki/qq/ (qq plugin territory)"})

        if rel == POLICY:
            policy = (fm, body)

        aud = fm.get("audience")
        if aud not in (None, "public", "private"):
            issues.append({"level": "warning", "message": f"{rel}: audience value {aud!r} outside public|private"})
        if aud == "public" and (rel.startswith("tmp/") or rel.startswith("archive/")):
            issues.append({"level": "info", "message": f"{rel}: audience: public on a non-content zone (tmp/ or archive/)"})

        if rel.startswith("qq/"):
            haystack = body + "\n" + json.dumps(fm, ensure_ascii=False)
            for pat in SECRET_PATTERNS:
                if pat.search(haystack):
                    issues.append({"level": "warning", "message": f"{rel}: credential-like string matched {pat.pattern!r}; openids and secrets belong in ~/.qq-cli/"})
                    break

    if policy is None:
        issues.append({"level": "warning", "message": f"wiki/{POLICY} missing (qq domain declaration page; created when absent)"})
    else:
        fm, _ = policy
        if fm.get("type") != "qq":
            issues.append({"level": "warning", "message": f"wiki/{POLICY}: missing `type: qq`"})
        block = fm.get("qq")
        if not isinstance(block, dict):
            issues.append({"level": "warning", "message": f"wiki/{POLICY}: missing the qq block mapping"})
        else:
            if not block.get("bot_appid"):
                issues.append({"level": "warning", "message": f"wiki/{POLICY}: qq block missing bot_appid"})
            pf = block.get("public_field")
            if pf and pf != "audience":
                issues.append({"level": "warning", "message": f"wiki/{POLICY}: public_field {pf!r} differs from the implemented convention (audience)"})

    return issues
