"""App-name -> productivity category mapping for the dashboard-only productivity view.

Edit CATEGORY_MAP to add process names as you notice them show up uncategorized
("other") in the Productivity tab. Matching is case-insensitive against the
process executable name reported by the tracker (e.g. "premiere pro.exe").
"""

CATEGORY_MAP = {
    "editing": [
        "premiere pro.exe", "afterfx.exe", "resolve.exe", "photoshop.exe",
        "audition.exe", "mediaencoder.exe", "illustrator.exe",
    ],
    "browser": [
        "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe",
    ],
    "communication": [
        "slack.exe", "discord.exe", "teams.exe", "outlook.exe",
    ],
}


def categorize(app_name: str) -> str:
    name = (app_name or "").lower()
    for category, names in CATEGORY_MAP.items():
        if name in names:
            return category
    return "other"
