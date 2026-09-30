"""Remove third-party GitHub references before public issue/PR/comment writes.

Keep source repositories in peers.json or repository documentation. Public discussion
uses plain project names so it cannot create cross-reference backlinks or mentions.
"""
import re

REPO = "kcnyu/clawock"
URL = re.compile(r"(?:https?://|www\.)?(?:github\.com|api\.github\.com/repos|raw\.githubusercontent\.com)/([\w.-]+)(?:/([\w.-]+))?[^\s<>\])}]*", re.I)
LINK = re.compile(r"!?\[([^\]\n]*)\]\(([^)\n]*)\)")
QUALIFIED = re.compile(r"(?<![\w/])([\w.-]+)/([\w.-]+)([#@])([\w.-]+)")
MENTION = re.compile(r"(?<![\w@])@([\w-]+)")


def sanitize(text):
    """Idempotent plain-text replacement; our own repository links remain intact."""
    text = text or ""

    def url(match):
        owner, project = match.group(1), match.group(2)
        if project and f"{owner}/{project}".lower() == REPO:
            return match.group(0)
        return f"{project or owner}（外部资料）"

    def link(match):
        target = match.group(2)
        if sanitize_urls(target) != target:
            return match.group(1) or sanitize_urls(target)
        return match.group(0)

    def sanitize_urls(value):
        value = re.sub(r"<([^<>\s]+)>", lambda m: url(u) if (u := URL.fullmatch(m.group(1))) else m.group(0), value)
        return URL.sub(url, value)

    text = LINK.sub(link, text)
    text = sanitize_urls(text)

    def qualified(match):
        owner, project, symbol, number = match.groups()
        if f"{owner}/{project}".lower() == REPO:
            return match.group(0)
        kind = "编号" if symbol == "#" else "版本"
        return f"{project}（外部{kind} {number}）"

    text = QUALIFIED.sub(qualified, text)
    return MENTION.sub(lambda m: m.group(1), text)


def validate(text):
    if sanitize(text) != text:
        raise ValueError("public GitHub text still contains third-party links or mentions")
    return text
