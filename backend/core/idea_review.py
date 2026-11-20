"""Split an analysis into independently reviewable proposals."""
import hashlib
import re


def parse_ideas(analysis_id, text):
    matches = list(re.finditer(r"(?m)^\s*#{1,4}\s+(.+?)\s*$", text or ""))
    ideas = []
    for index, match in enumerate(matches):
        title = re.sub(r"^\d+[.)]\s*", "", match.group(1).strip().strip("*"))
        body = text[match.end():matches[index + 1].start() if index + 1 < len(matches) else len(text)].strip()
        key = hashlib.sha256(f"{analysis_id}\0{index}\0{match.group(0)}\0{body}".encode()).hexdigest()[:24]
        ideas.append({"id": key, "title": title, "body": body})
    return ideas
