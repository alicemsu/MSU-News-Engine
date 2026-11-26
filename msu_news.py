import os
import re
import json
import time
import calendar
from difflib import SequenceMatcher
from collections import Counter
import requests
import feedparser
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlsplit
from googlenewsdecoder import gnewsdecoder
webhook = os.environ["DISCORD_WEBHOOK_URL"]
if not webhook:
  raise SystemExit("Missing Discord secret")
state = Path("published.json")
seen = set(json.loads(state.read_text())) if state.exists() else set()
limit = 3
max_attempts = 14
session = requests.Session()
session.headers["User-Agent"] = "MSU-News-Engine/1.4.1"
from msu_sources import (
  regions, DIRECT_FEEDS, web_queries, fingerprint, canonical, clean,
  public_url, is_google, useful_summary, normalize, reddit_title, franchise,
  technical, search_source, unwrap, relevant, topic_key, repair_text,
  suspicious_text, metadata, category, next_news_search, regional_news, next_web_search,
)
control_path = Path("news_control.json")
control = json.loads(control_path.read_text()) if control_path.exists() else {}
order = tuple(regions)
slot = int(control.get("global_google_slot", control.get("next_region", 0)))
def save_control():
  control_path.write_text(json.dumps(control, indent=2))
def google_backoff():
  control["google_pause_until"] = time.time() + 3600
  save_control()
feeds = list(DIRECT_FEEDS)
alerts = os.environ.get("GOOGLE_ALERTS_RSS_URLS", "").splitlines()
alerts = [u.strip() for u in alerts if u.strip().startswith("https://www.google.com/alerts/feeds/")][:20]
if alerts and time.time() >= float(control.get("alerts_pause_until", 0)):
  idx = int(control.get("alerts_slot", 0)) % len(alerts)
  for n in range(min(3, len(alerts))):
    i = (idx+n) % len(alerts)
    feeds.append(("Google Alerts " + str(i+1), alerts[i], False))
  control["alerts_slot"] = (idx+min(3,len(alerts))) % len(alerts)
  save_control()
if time.time() >= float(control.get("bing_pause_until", 0)):
  idx = int(control.get("global_web_slot", 0))
  lang, query = next_web_search(idx)
  print("Web search:", lang, query)
  feeds.append(("Bing community", "https://www.bing.com/search?" + urlencode({"q": query, "format": "rss", "setlang": regions[lang][1], "cc": regions[lang][2]}), False))
  control["global_web_slot"] = idx + 1
  save_control()
else:
  print("Bing cooldown active")
if time.time() >= float(control.get("bing_news_pause_until", 0)):
  idx = int(control.get("global_bing_news_slot", 30))
  lang, secondary = next_news_search(idx)
  query, hl, gl, _ = regional_news(lang, secondary)
  print("Bing News scope:", "SNK/Neo Geo" if secondary else "Metal Slug", lang)
  feeds.append(("Bing News " + lang, "https://www.bing.com/news/search?" + urlencode({"q": query, "format": "rss", "setlang": hl, "cc": gl}), False))
  control["global_bing_news_slot"] = idx + 1
  save_control()
if time.time() >= float(control.get("google_pause_until", 0)):
  lang, secondary = next_news_search(slot)
  print("Google region:", lang, "SNK/Neo Geo" if secondary else "Metal Slug")
  query, hl, gl, ceid = regional_news(lang, secondary)
  url = "https://news.google.com/rss/search?" + urlencode({
    "q": "(" + query + ") when:7d", "hl": hl, "gl": gl, "ceid": ceid
  })
  feeds.append(("Google News " + lang, url, True))
  control["global_google_slot"] = slot + 1
  save_control()
else:
  print("Google cooldown active; other sources remain enabled")
topic_state = Path("published_topics.json")
topics = json.loads(topic_state.read_text()) if topic_state.exists() else {}
topics = {k: v for k, v in topics.items() if time.time() - v < 604800}
if not control.get("v13_migrated"):
  if seen and "metal-slug-movie-writer" not in topics:
    topics["metal-slug-movie-writer"] = time.time()
    topic_state.write_text(json.dumps(topics, indent=2))
  control["v13_migrated"] = True
  save_control()
recent_path = Path("recent_titles.json")
recent = json.loads(recent_path.read_text()) if recent_path.exists() else []
recent = [x for x in recent if time.time() - x["time"] < 604800][-300:]
def similar_title(title):
  t = normalize(title)
  def versions(v):
    return re.findall(r"\b(?:v|version|versión)\s*([0-9]+(?:\s+[0-9]+)*)", v)
  return len(t) >= 20 and any(
    versions(t) == versions(x["title"]) and SequenceMatcher(None, t, x["title"], autojunk=False).ratio() >= 0.88
    for x in recent
  )
candidates = []
for source, url, google in feeds:
  stats = Counter()
  try:
    if source.startswith("Google Alerts ") and time.time() < float(control.get("alerts_pause_until", 0)):
      continue
    response = session.get(url, timeout=20)
    if response.status_code in (429, 403):
      print("HTTP restriction:", source, response.status_code)
      if google:
        google_backoff()
        break
      if source.startswith("Google Alerts "):
        control["alerts_pause_until"] = time.time() + 3600
        save_control()
      if source == "Bing community" or source.startswith("Bing News "):
        k = "bing_pause_until" if source == "Bing community" else "bing_news_pause_until"
        control[k] = time.time() + 3600
        save_control()
      continue
    response.raise_for_status()
    feed = feedparser.parse(response.content)
    print("Feed:", source, "entries=", len(feed.entries))
    if not feed.version and not feed.entries:
      print("Invalid RSS response:", source)
      k = ("google_pause_until" if google else "bing_pause_until" if source == "Bing community" else "bing_news_pause_until" if source.startswith("Bing News ") else "alerts_pause_until" if source.startswith("Google Alerts ") else "")
      if k:
        control[k] = time.time() + 3600
        save_control()
      continue
    for entry in feed.entries:
      title = repair_text(entry.get("title", ""))
      link = entry.get("link", "")
      summary = repair_text(entry.get("summary", ""))
      if not title or not public_url(link):
        stats["invalid"] += 1
        continue
      published = entry.get("published_parsed") or entry.get("updated_parsed")
      stamp = calendar.timegm(published) if published else 0
      if not search_source(source) and (not stamp or not -3600 <= time.time() - stamp <= (2592000 if technical(title) else 604800)):
        stats["date"] += 1
        continue
      if search_source(source):
        link = unwrap(link)
        if not public_url(link):
          stats["invalid"] += 1
          continue
      publisher = entry.get("source", {}).get("title", source)
      if search_source(source):
        publisher = urlsplit(link).hostname or source
        if publisher == "reddit.com" or publisher.endswith(".reddit.com"):
          if "/comments/" not in urlsplit(link).path:
            stats["unrelated"] += 1
            continue
          publisher = "Reddit - Comunidad"
          title = reddit_title(title)
      if google and title.endswith(" - " + publisher):
        title = title[:-(len(publisher) + 3)]
      if not relevant(title, summary, source):
        stats["unrelated"] += 1
        continue
      key = fingerprint(title)
      if key in seen or similar_title(title):
        stats["duplicate"] += 1
        continue
      rss_image = ""
      if not google:
        for media in entry.get("media_content", []) + entry.get("media_thumbnail", []) + entry.get("enclosures", []):
          if (media.get("url") or media.get("href")) and media.get("medium", "image") == "image" and (not media.get("type") or media["type"].startswith("image/")):
            rss_image = urljoin(link, media.get("url") or media.get("href"))
            break
      candidates.append((stamp, google, title, link, summary, publisher, key, rss_image, source))
      stats["candidate"] += 1
  except Exception as error:
    print("Feed error:", source, type(error).__name__)
  finally:
    print("Feed results:", source, dict(stats))
  time.sleep(3)
print("Candidates:", len(candidates))
candidates.sort(key=lambda x: (category(x[2], x[4], x[8]) == "metal-slug", bool(technical(x[2])), x[0]), reverse=True)
print("Candidate categories:", dict(Counter(category(x[2], x[4], x[8]) for x in candidates)))
sent = 0
secondary_sent = 0
attempts = 0
undated_sent = 0
source_sent = Counter()
for stamp, google, title, link, summary, publisher, key, rss_image, source in candidates:
  if sent >= limit or attempts >= max_attempts:
    break
  if source_sent[source] >= 2:
    continue
  if category(title, summary, source) == "snk-neogeo" and secondary_sent >= 1:
    continue
  if key in seen or fingerprint(canonical(link)) in seen or fingerprint(link) in seen:
    continue
  if google and time.time() < float(control.get("google_pause_until", 0)):
    continue
  topic = topic_key(title, summary)
  if topic and topic in topics:
    print("Skip similar event:", topic)
    continue
  attempts += 1
  original = link
  image = rss_image
  if search_source(source):
    stamp = 0
    summary = ""
    image = ""
  try:
    if google:
      if time.time() < float(control.get("google_pause_until", 0)):
        continue
      decoded = gnewsdecoder(link, interval=2, timeout=12)
      resolved = decoded.get("decoded_url", "")
      if not (decoded.get("success") or decoded.get("status")) or not resolved or not public_url(resolved) or is_google(resolved):
        print("Decode failed:", publisher, str(decoded.get("message", "unknown"))[:180])
        if "429" in str(decoded.get("message", "")):
          google_backoff()
          continue
        continue
      original = resolved
      print("Decoded:", publisher)
    if not public_url(original):
      continue
    new_title, description, page_image, page_stamp, final_url = metadata(session, original)
    original = final_url
    if not public_url(original) or is_google(original):
      continue
    if search_source(source) or page_stamp:
      stamp = page_stamp
    title = repair_text(new_title) or title
    if publisher == "Reddit - Comunidad":
      title = reddit_title(title)
    description = repair_text(description)
    if useful_summary(description, title, publisher):
      summary = description
    image = page_image or image
  except Exception as error:
    print("Metadata unavailable:", publisher, type(error).__name__)
  if stamp and not -3600 <= time.time() - stamp <= (2592000 if technical(title) else 604800):
    print("Skip old article:", publisher)
    continue
  if search_source(source):
    if not stamp and (source != "Bing community" or not technical(title) or undated_sent):
      print("Skip unverified date:", publisher)
      continue
  kind = category(title, summary, source)
  if not kind:
    print("Skip unrelated article:", publisher, title[:120])
    continue
  if kind == "snk-neogeo" and secondary_sent >= 1:
    print("Skip complementary quota:", publisher)
    continue
  extra_key = fingerprint(title)
  url_key = fingerprint(canonical(original))
  topic = topic or topic_key(title, summary)
  if extra_key in seen or url_key in seen or fingerprint(original) in seen or similar_title(title) or (topic and topic in topics):
    print("Skip duplicate:", publisher)
    continue
  if not image or not public_url(image) or re.search(r"(?:logo|favicon|placeholder|default[-_]?share)", urlsplit(image).path, re.I) or not useful_summary(summary, title, publisher) or is_google(original) or suspicious_text(title) or suspicious_text(summary):
    print("Skip incomplete:", publisher, "image=", bool(image), "description=", useful_summary(summary, title, publisher))
    continue
  print("Ready:", publisher, "image=yes description=yes")
  embed = {
    "title": title[:250],
    "url": original,
    "description": summary[:500] or "Consulta el artículo original.",
    "color": 16744448 if kind == "metal-slug" else 3447003,
    "author": {"name": publisher[:200]},
    "footer": {"text": "Metal Slug Unity | " + ("Metal Slug" if kind == "metal-slug" else "SNK / Neo Geo") + " | " + ("Hallazgo técnico sin fecha verificada" if not stamp else "Comunidad" if publisher == "Reddit - Comunidad" else "News Network")}
  }
  if stamp:
    embed["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stamp))
  if image.startswith(("https://", "http://")):
    embed["image"] = {"url": image}
  try:
    response = requests.post(
      webhook,
      json={
        "embeds": [embed],
        "allowed_mentions": {"parse": []}
      },
      timeout=20
    )
    if response.status_code not in (200, 204):
      print("Discord HTTP:", response.status_code)
      raise SystemExit("Discord publication failed")
  except requests.RequestException:
    raise SystemExit("Discord connection error")
  seen.update([key, extra_key, url_key])
  state.write_text(json.dumps(sorted(seen), indent=2))
  if topic:
    topics[topic] = time.time()
    topic_state.write_text(json.dumps(topics, indent=2))
  recent.append({"title": normalize(title), "time": time.time()})
  recent_path.write_text(json.dumps(recent[-300:], ensure_ascii=False, indent=2))
  sent += 1
  secondary_sent += int(kind == "snk-neogeo")
  source_sent[source] += 1
  undated_sent += int(not stamp)
  time.sleep(3)
print("Published:", sent, "Metal Slug:", sent-secondary_sent, "SNK/Neo Geo:", secondary_sent)
