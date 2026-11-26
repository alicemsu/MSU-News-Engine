import re
import hashlib
import unicodedata
import base64
import ipaddress
import socket
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit, parse_qsl

base = '"Metal Slug" OR "MetalSlug"'
regions = {
  "en": (base, "en-US", "US", "US:en"),
  "es": (base, "es-419", "MX", "MX:es-419"),
  "ja": (base + ' OR "メタルスラッグ"', "ja", "JP", "JP:ja"),
  "zh-CN": (base + ' OR "合金弹头"', "zh-CN", "SG", "SG:zh-Hans"),
  "zh-TW": (base + ' OR "合金彈頭"', "zh-TW", "TW", "TW:zh-Hant"),
  "ko": (base + ' OR "메탈슬러그" OR "메탈 슬러그"', "ko", "KR", "KR:ko"),
  "ar": (base + ' OR "ميتال سلغ" OR "ميتال سلاج" OR "ميتال سلاغ" OR "ميتال سلق"', "ar", "SA", "SA:ar"),
  "pt": (base, "pt-BR", "BR", "BR:pt-419"),
  "fr": (base, "fr", "FR", "FR:fr"),
  "th": (base + ' OR "เมทัลสลัก" OR "เมทัล สลัก" OR "เมทัลสลักก์"', "th", "TH", "TH:th"),
  "vi": (base + ' OR "Rambo lùn"', "vi", "VN", "VN:vi"),
  "id": (base, "id", "ID", "ID:id"),
  "ru": (base + ' OR "Метал Слаг"', "ru", "RU", "RU:ru"),
  "de": (base, "de", "DE", "DE:de"),
  "it": (base, "it", "IT", "IT:it"),
}

DIRECT_FEEDS = [
  ("Gematsu", "https://www.gematsu.com/feed", False),
  ("Time Extension", "https://www.timeextension.com/feeds/news", False),
  ("Game*Spark", "https://www.gamespark.jp/rss20/index.rdf", False),
  ("Bahamut GNN", "https://gnn.gamer.com.tw/rss_utf8.xml", False),
  ("Ruliweb", "https://bbs.ruliweb.com/news/rss", False),
  ("Adrenaline", "https://www.adrenaline.com.br/feed/", False),
  ("Nintenduo", "https://nintenduo.com/feed", False),
  ("RetroRGB", "https://retrorgb.com/category/retrorgb/feed", False),
  ("Time Extension Metal Slug", "https://www.timeextension.com/feeds/latest/tags/metal-slug", False),
  ("Time Extension Neo Geo", "https://www.timeextension.com/feeds/latest/tags/neo-geo", False),
]
tech = {
  "en": '"ROM hack" OR romhack OR IPS OR BPS OR FBNeo OR HBMAME OR "native port" OR fangame',
  "es": 'hack OR parche OR modificaciones OR port OR fangame',
  "ja": '改造 OR ハック OR パッチ OR 移植 OR ファンゲーム',
  "zh-CN": '改版 OR 修改版 OR 补丁 OR 移植 OR 同人 OR FBNeo',
  "zh-TW": '改版 OR 修改版 OR 補丁 OR 移植 OR 同人 OR FBNeo',
  "ko": '개조 OR 롬핵 OR 패치 OR 이식 OR 팬게임',
  "ar": 'تعديل OR تعديلات OR هاك OR باتش OR ريميك',
  "pt": 'hack OR modificações OR tradução OR port OR fangame',
  "fr": 'hack OR modification OR patch OR portage OR fangame',
  "th": 'แฮก OR ม็อด OR แพตช์ OR พอร์ต OR hack',
  "vi": 'bản mod OR bản hack OR bản vá OR port',
  "id": 'modifikasi OR hack OR patch OR port',
  "ru": 'ромхак OR модификация OR патч OR порт OR хак',
  "de": 'ROM-Hack OR Modifikation OR Patch OR Portierung',
  "it": 'hack OR modifica OR patch OR porting',
}
web_queries = [(k, '(' + q[0] + ') (' + tech[k] + ')') for k,q in regions.items()]
web_queries += [("en", q) for q in (
  '"Metal Slug" (prototype OR "location test" OR preservation OR speedrun)',
  '"Metal Slug" (recompilation OR decompilation OR "reverse engineering")',
  '(mslug OR mslug2 OR mslug3 OR mslug4 OR mslug5 OR mslugx) (IPS OR BPS OR romhack OR hack)',
  '"Metal Slug" (fangame OR mod OR "new characters" OR "4 players")',
  '"Metal Slug" (site:romhacking.net OR site:romhack.ing OR site:romhackplaza.org)',
  '"Metal Slug" (site:bilibili.com OR site:youtube.com OR site:arcade-projects.com)',
)]

web_queries.insert(1, ("en", 'site:reddit.com "Metal Slug"'))

extra_names = {
  "en": '', "es": '', "pt": '', "fr": '', "de": '', "it": '',
  "ja": ' OR "ネオジオ" OR "餓狼伝説" OR "サムライスピリッツ" OR "龍虎の拳" OR "ザ・キング・オブ・ファイターズ"',
  "zh-CN": ' OR "拳皇" OR "饿狼传说" OR "侍魂" OR "龙虎之拳"',
  "zh-TW": ' OR "拳皇" OR "餓狼傳說" OR "侍魂" OR "龍虎之拳"',
  "ko": ' OR "네오지오" OR "킹 오브 파이터즈" OR "아랑전설" OR "사무라이 쇼다운"',
  "ar": ' OR "نيو جيو" OR "كينغ أوف فايترز"',
  "ru": ' OR "Нео Гео"', "th": ' OR "นีโอจีโอ"', "vi": '', "id": '',
}
universe_base = '"SNK" OR "Neo Geo" OR "NeoGeo" OR "The King of Fighters" OR "Fatal Fury" OR "Samurai Shodown" OR "Art of Fighting" OR "Garou Mark of the Wolves" OR "World Heroes" OR "The Last Blade"'

def regional_news(lang, secondary=False):
  query, hl, gl, ceid = regions[lang]
  return ((universe_base + extra_names.get(lang, "")) if secondary else query, hl, gl, ceid)

def next_news_search(index):
  order = tuple(regions)
  cycle, slot = divmod(index, len(order))
  lang = order[slot]
  return lang, cycle % 3 == 2

extra_web_queries = [(lang, '(' + regional_news(lang, True)[0] + ') (' + tech[lang] + ')') for lang in regions]
extra_web_queries.append(("en", 'site:reddit.com ("Neo Geo" OR "The King of Fighters" OR "Fatal Fury" OR "Samurai Shodown")'))

def next_web_search(index):
  if index % 3 == 2:
    return extra_web_queries[(index // 3) % len(extra_web_queries)]
  return web_queries[(index // 3 * 2 + index % 3) % len(web_queries)]

def clean(value):
  return BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True)
def fingerprint(value):
  value = re.sub(r"[^\w]+", "", value.casefold())
  return hashlib.sha256(value.encode()).hexdigest()
def is_google(url):
  return (urlsplit(url).hostname or "").lower() == "news.google.com"
def public_url(url):
  try:
    p = urlsplit(url)
    return p.scheme in ("http", "https") and bool(p.hostname) and not p.username and not p.password and p.port in (None, 80, 443)
  except ValueError:
    return False
def get_page(session, url):
  for _ in range(6):
    if not public_url(url):
      raise ValueError("Invalid article URL")
    host = urlsplit(url).hostname
    if not all(ipaddress.ip_address(x[4][0]).is_global for x in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)):
      raise ValueError("Non-public article host")
    with session.get(url, timeout=12, allow_redirects=False, stream=True) as r:
      if r.is_redirect:
        url = urljoin(url, r.headers["Location"])
        continue
      r.raise_for_status()
      if "html" not in r.headers.get("Content-Type", "text/html").lower():
        raise ValueError("Not an HTML article")
      chunks = bytearray()
      for chunk in r.iter_content(65536):
        chunks.extend(chunk)
        if len(chunks) > 4000000:
          raise ValueError("Article too large")
      r._content = bytes(chunks)
      return r
  raise ValueError("Too many redirects")
def canonical(url):
  p = urlsplit(url)
  query = urlencode([(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in ("fbclid", "gclid")])
  return urlunsplit((p.scheme, p.netloc.lower(), p.path.rstrip("/"), query, ""))
def useful_summary(summary, title, publisher):
  a, b = fingerprint(summary), fingerprint(title)
  normalized = re.sub(r"[^\w]+", "", summary.casefold())
  headline = re.sub(r"[^\w]+", "", title.casefold())
  source = re.sub(r"[^\w]+", "", publisher.casefold())
  return len(summary) >= 30 and a != b and normalized not in (headline + source, source + headline)
def normalize(value):
  value = unicodedata.normalize("NFKC", value).casefold()
  return " ".join(re.findall(r"[^\W_]+", value, re.UNICODE))
def reddit_title(value):
  return re.sub(r"\s*[:|–—-]\s*(?:r/[a-zA-Z0-9_]+|reddit)\s*$", "", value, flags=re.I).strip()
def franchise(value):
  h = normalize(value)
  aliases = ("メタルスラッグ", "メタル スラッグ", "合金弹头", "合金彈頭", "메탈슬러그", "메탈 슬러그", "ميتال سلغ", "ميتال سلاج", "ميتال سلاغ", "ميتال سلق", "ميتال سلاگ", "เมทัลสลัก", "เมทัล สลัก", "метал слаг", "метал слуг", "金属弹头", "金屬彈頭", "ميتل سلغ", "میتال اسلاگ", "メタル・スラッグ", "металслаг", "메탈 슬러그", "เมทัลสลักก์")
  return bool(re.search(r"(?<!\w)(?:metal\s*slug(?:\d+|x{1,2})?|mslug(?:[1-7x][a-z0-9]{0,10}|[a-z]{1,3}[0-9]?)?|rambo lùn)(?!\w)", h)) or any(x in unicodedata.normalize("NFKC", value).casefold() for x in aliases)
def generic_update(title):
  h = normalize(title)
  emulator = r"(?:fbneo|finalburn neo|fightcade|hbmame|mame|retroarch|flycast)"
  return bool(re.match(r"^(?:new\s+)?" + emulator + r"\s+(?:v?\d|release|update|changelog|commits|actualizaci[oó]n|version|versión|nightly|build|actualizado|new version)", h) or re.match(r"^(?:new\s+)?(?:release|update|version|versión|actualización)\s+(?:of\s+|de\s+)?" + emulator + r"\b", h))

def universe(value):
  h = normalize(value)
  titles = (
    "the king of fighters", "king of fighters", "fatal fury", "samurai shodown",
    "samurai spirits", "art of fighting", "garou mark of the wolves", "world heroes",
    "the last blade", "kizuna encounter", "savage reign", "real bout fatal fury",
    "kof maximum impact", "snk vs capcom", "svc chaos", "shock troopers",
    "king of the monsters", "sengoku", "burning fight", "ninja combat",
    "ninja commando", "cyber lip", "mutation nation", "robo army",
    "neo bomberman", "last resort", "aero fighters", "sonic wings",
    "street hoop", "super sidekicks", "breakers revenge",
    "neo drift out",
    "twinkle star sprites", "blazing star", "pulstar", "neo turf masters",
    "big tournament golf", "waku waku 7", "magical drop", "windjammers",
  )
  aliases = ("ネオジオ", "餓狼伝説", "サムライスピリッツ", "龍虎の拳", "キングオブファイターズ", "キング オブ ファイターズ", "拳皇", "饿狼传说", "餓狼傳說", "侍魂", "龙虎之拳", "龍虎之拳", "네오지오", "킹 오브 파이터즈", "아랑전설", "사무라이 쇼다운", "نيو جيو", "كينغ أوف فايترز", "нео гео", "นีโอจีโอ")
  if any(re.search(r"(?<!\w)" + re.escape(x) + r"(?!\w)", h) for x in titles):
    return True
  if any(x in h for x in aliases):
    return True
  if re.search(r"(?<!\w)neo\s*geo(?!\w)", h):
    return True
  if re.search(r"(?<!\w)kof\s*(?:[0-9]{1,4}|xv|xiv|xiii|xi|xii)(?!\w)", h):
    return True
  return bool(re.search(r"(?<!\w)snk(?!\w)", h) and re.search(r"(?<!\w)(?:game\w*|arcade|fighting|videogame\w*|videojuego\w*|consola\w*|gaming|licens\w*|licencia\w*|developer\w*|publisher\w*|jogos?|jeux|spiel\w*|ゲーム|游戏|遊戲|게임)(?!\w)", h))

def category(title, summary="", source=""):
  if generic_update(title):
    return ""
  if franchise(title):
    return "metal-slug"
  if universe(title):
    return "snk-neogeo"
  if (universe(summary) or (re.search(r"\bsnk\b", normalize(title)) and universe(title + " " + summary))) and re.search(r"(?<!\w)(?:release\w*|launch\w*|lanzamiento\w*|port\w*|remake\w*|remaster\w*|reissue\w*|cartridge\w*|cartucho\w*|arcade|collection|colecci[oó]n|hack\w*|patch\w*|parche\w*|modification\w*|announc\w*|anuncio\w*|game\w*|jogo\w*|videojuego\w*|発売|發售|发售|출시)(?!\w)", normalize(title)):
    return "snk-neogeo"
  return ""

def technical(title):
  h = unicodedata.normalize("NFKC", title).casefold()
  return bool(re.search(r"\b(?:romhacks?|hacks?|mods?|patch(?:es)?|ips|bps|recompil\w*|decompil\w*|ports?|fangames?|prototyp\w*|modific\w*|parches?|reverse engineering|location test)\b", h)) or any(x in h for x in ("改版", "修改", "改造", "移植", "补丁", "補丁", "개조", "롬핵", "패치", "이식", "تعديل", "патч", "ромхак", "ม็อด", "แฮก", "bản mod", "bản hack"))
def search_source(source):
  return source == "Bing community" or source.startswith(("Bing News ", "Google Alerts "))
def unwrap(link):
  p = urlsplit(link)
  q = dict(parse_qsl(p.query))
  host = p.hostname or ""
  if host in ("google.com", "www.google.com") and p.path == "/url":
    return q.get("url") or q.get("q") or ""
  if host in ("bing.com", "www.bing.com"):
    target = q.get("url", "") or q.get("u", "")
    if target.startswith("a1"):
      try:
        v = target[2:]
        target = base64.urlsafe_b64decode(v + "=" * (-len(v) % 4)).decode()
      except Exception:
        return ""
    return target
  return link
def relevant(title, summary="", source=""):
  return bool(category(title, summary, source))
def topic_key(title, summary):
  h = normalize(title)
  t = normalize(title + " " + summary)
  movie = ("movie", "film", "película", "pelicula", "映画", "実写", "电影", "電影", "真人", "영화", "실사", "live action", "cine", "filme", "cinéma", "فيلم", "سينما", "phim", "ภาพยนตร์", "фильм", "кино", "verfilmung", "pellicola")
  if franchise(title) and any(x in h for x in movie):
    new_detail = ("trailer", "teaser", "tráiler", "reparto confirmado", "casting", "cast revealed", "cast announced", "director announced", "fecha de estreno", "release date", "予告", "キャスト", "公開日", "预告", "預告", "演员阵容", "演員陣容", "上映日期", "예고편", "캐스팅", "개봉일", "data de estreia", "date de sortie", "bande annonce", "موعد العرض", "طاقم التمثيل", "الإعلان التشويقي", "ngày công chiếu", "วันฉาย", "tanggal rilis", "дата выхода", "трейлер", "starttermin", "data di uscita")
    writers = ("writer", "screenplay", "screenwriter", "guionista", "guion", "morosini", "脚本", "编剧", "編劇", "각본", "roteirista", "scénariste", "сценарист", "drehbuch", "sceneggiat", "كاتب")
    if not any(x in h for x in new_detail) and any(x in t for x in writers):
      return "metal-slug-movie-writer"
  return ""
def suspicious_text(value):
  if not value:
    return False
  if "\ufffd" in value or re.search(r"[\x80-\x9f]", value):
    return True
  return len(re.findall(r"[ÃÂãæåçéäèïðì][\u0080-\u00bf\u2000-\u203f€™œŠšŽžŸ]", value)) >= 2
def repair_text(value):
  value = clean(value)
  if not suspicious_text(value):
    return value
  for encoding in ("cp1252", "latin-1"):
    try:
      repaired = value.encode(encoding).decode("utf-8")
      if not suspicious_text(repaired):
        return repaired
    except (UnicodeEncodeError, UnicodeDecodeError):
      pass
  return ""
def parse_html(response):
  raw = response.content
  try:
    return BeautifulSoup(raw.decode("utf-8-sig"), "html.parser")
  except UnicodeDecodeError:
    pass
  soup = BeautifulSoup(raw, "html.parser")
  declared = re.search(r"charset\s*=\s*[\"']?([\w.-]+)", response.headers.get("Content-Type", ""), re.I)
  has_meta = bool(re.search(br"<meta[^>]+charset\s*=", raw[:16384], re.I))
  if declared and not has_meta:
    try:
      decoded = raw.decode(declared.group(1))
      if not suspicious_text(decoded[:5000]):
        return BeautifulSoup(decoded, "html.parser")
    except (LookupError, UnicodeDecodeError):
      pass
  if suspicious_text(soup.get_text(" ", strip=True)[:5000]):
    try:
      from charset_normalizer import from_bytes
      best = from_bytes(raw).best()
      if best and not suspicious_text(str(best)[:5000]):
        return BeautifulSoup(str(best), "html.parser")
    except Exception:
      pass
  return soup
def metadata(session, url):
  response = get_page(session, url)
  soup = parse_html(response)
  def meta(*keys):
    for key in keys:
      tag = soup.find("meta", attrs={"property": key})
      if not tag:
        tag = soup.find("meta", attrs={"name": key})
      if tag and tag.get("content"):
        return tag["content"]
    return ""
  image = meta("og:image:secure_url", "og:image", "twitter:image", "twitter:image:src")
  if not image:
    tag = soup.find("link", rel="image_src")
    image = tag.get("href", "") if tag else ""
  if not image:
    article = soup.find("article")
    tag = article.find("img") if article else None
    image = (tag.get("data-src") or tag.get("src") or "") if tag else ""
  if image and re.search(r"(?:logo|favicon|placeholder|default[-_]?share|reddit[-_]?icon)", urlsplit(image).path, re.I):
    image = ""
  description = meta("og:description", "description", "twitter:description")
  if not description:
    article = soup.find("article")
    if article:
      description = next((p.get_text(" ", strip=True) for p in article.find_all("p") if len(p.get_text(" ", strip=True)) >= 80), "")
  date = meta("article:published_time", "datePublished", "date", "og:published_time")
  if not date:
    match = re.search(r'"(?:datePublished|uploadDate|dateCreated)"\s*:\s*"([^"]+)"', str(soup))
    date = match.group(1) if match else ""
  if not date:
    tag = soup.find("time", attrs={"datetime": True})
    date = tag.get("datetime", "") if tag else ""
  try:
    dt = datetime.fromisoformat(date.replace("Z", "+00:00"))
    stamp = (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()
  except (ValueError, OverflowError):
    stamp = 0
  return meta("og:title", "twitter:title") or (soup.title.get_text(" ", strip=True) if soup.title else ""), description, urljoin(response.url, image) if image else "", stamp, response.url
