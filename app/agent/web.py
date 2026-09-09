"""Bounded public HTTPS reader with DNS filtering at connection resolution."""
import asyncio
import hashlib
import ipaddress
import json
import socket
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit, urljoin, urldefrag
from urllib.robotparser import RobotFileParser

import aiohttp
from bs4 import BeautifulSoup

from app.storage import now


class ToolFailure(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def check_url(url, domains):
    try:
        p = urlsplit(url)
        if p.scheme != 'https' or p.username or p.password or p.port not in (None, 443) or p.hostname not in domains or len(url) > 2048:
            raise ToolFailure('blocked_url')
        try:
            ipaddress.ip_address(p.hostname)
        except ValueError:
            return urldefrag(url)[0]
    except (ValueError, TypeError):
        pass
    raise ToolFailure('blocked_url')


class PublicResolver(aiohttp.abc.AbstractResolver):
    async def resolve(self, host, port=0, family=socket.AF_INET):
        entries = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
        if not entries or any(not ipaddress.ip_address(e[4][0]).is_global for e in entries):
            raise ToolFailure('blocked_url')
        return [dict(hostname=host, host=e[4][0], port=port, family=e[0], proto=e[2], flags=socket.AI_NUMERICHOST) for e in entries]

    async def close(self):
        pass


class WebReader:
    def __init__(self, reserve_network):
        self.reserve_network = reserve_network
        self.robots = {}
        self.last_request = {}

    async def request(self, url, domains, follow_redirects=False, before_redirect=None):
        # A new connector per request pins the actual socket to checked addresses.
        # No proxies, no cookies, no redirects delegated to the HTTP library.
        for redirect in range(4):
            url = check_url(url, domains)
            host = urlsplit(url).hostname
            await asyncio.sleep(max(0, 1 - (time.monotonic()-self.last_request.get(host, 0))))
            self.reserve_network()
            self.last_request[host] = time.monotonic()
            connector = aiohttp.TCPConnector(resolver=PublicResolver(), use_dns_cache=False)
            async with aiohttp.ClientSession(connector=connector, trust_env=False,
                    cookie_jar=aiohttp.DummyCookieJar(), timeout=aiohttp.ClientTimeout(total=15),
                    headers={'User-Agent': 'LockinBot/0.1'}) as client:
                async with client.get(url, allow_redirects=False) as response:
                    if response.status in {301, 302, 303, 307, 308}:
                        if not follow_redirects:
                            raise ToolFailure('document_redirect_rejected')
                        if redirect == 3 or 'Location' not in response.headers:
                            raise ToolFailure('redirect_limit')
                        url = check_url(urljoin(url, response.headers['Location']), domains)
                        if before_redirect:
                            await before_redirect(url)
                        continue
                    raw = bytearray()
                    async for chunk in response.content.iter_chunked(16384):
                        raw.extend(chunk)
                        if len(raw) > 1048576:
                            raise ToolFailure('too_large')
                    return url, response.status, response.headers.get('Content-Type', ''), raw.decode('utf-8', errors='replace')
        raise ToolFailure('redirect_limit')

    async def rules_for(self, url, domains):
        root = 'https://' + urlsplit(url).netloc
        if root not in self.robots:
            _, status, _, text = await self.request(root + '/robots.txt', domains, follow_redirects=True)
            if status == 404:
                text = 'User-agent: *\nDisallow:'
            elif status != 200:
                raise ToolFailure('robots_unavailable')
            parser = RobotFileParser()
            parser.parse(text.splitlines())
            self.robots[root] = parser
        return self.robots[root]

    async def ensure_allowed(self, url, domains):
        rules = await self.rules_for(url, domains)
        if not rules.can_fetch('LockinBot', url):
            raise ToolFailure('robots_denied')
        delay = rules.crawl_delay('LockinBot') or 1
        if delay > 1:
            await asyncio.sleep(max(0, delay-(time.monotonic()-self.last_request.get(urlsplit(url).hostname, 0))))

    @staticmethod
    def published_date(soup):
        selectors = [
            ('meta', {'property':'article:published_time'}),
            ('meta', {'name':'date'}), ('meta', {'name':'pubdate'}),
            ('meta', {'itemprop':'datePublished'}),
        ]
        for tag, attrs in selectors:
            node = soup.find(tag, attrs=attrs)
            value = node.get('content') if node else None
            if value:
                return value[:40]
        dated = soup.find('time', attrs={'datetime':True})
        if dated and dated.get('datetime'):
            return dated['datetime'][:40]
        for node in soup.find_all('script', attrs={'type':'application/ld+json'})[:10]:
            try:
                value = json.loads(node.string or '{}')
            except (json.JSONDecodeError, TypeError):
                continue
            values = value if isinstance(value, list) else [value]
            for item in values:
                date = item.get('datePublished') if isinstance(item, dict) else None
                if isinstance(date, str) and date:
                    return date[:40]
        return None

    @staticmethod
    def feed_content(text, final):
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            raise ToolFailure('unsupported_content') from None
        def local(tag):
            return tag.rsplit('}', 1)[-1].lower()
        title = next((node.text.strip() for node in root.iter()
                      if local(node.tag) == 'title' and node.text and node.text.strip()), final)
        entries = [node for node in root.iter() if local(node.tag) in {'item','entry'}][:20]
        chunks, published = [], None
        for entry in entries:
            fields = {}
            for node in entry.iter():
                name = local(node.tag)
                if name in {'title','description','summary','content','published','updated','pubdate'}:
                    value = ''.join(node.itertext()).strip()
                    if value and name not in fields:
                        fields[name] = BeautifulSoup(value, 'html.parser').get_text(' ', strip=True)
            chunks.append(' — '.join(fields[key] for key in
                                      ('title','description','summary','content') if fields.get(key)))
            published = published or next((fields.get(key) for key in
                                            ('published','updated','pubdate') if fields.get(key)), None)
        content = ' '.join(chunk for chunk in chunks if chunk)
        if not content:
            raise ToolFailure('unsupported_content')
        return title[:200], content, published[:40] if published else None

    async def read(self, url, domains):
        url = check_url(url, domains)
        await self.ensure_allowed(url, domains)
        final, status, mime, text = await self.request(
            url, domains, follow_redirects=True,
            before_redirect=lambda target: self.ensure_allowed(target, domains))
        if status != 200:
            raise ToolFailure('rate_limited' if status == 429 else 'unavailable')
        normalized_mime = mime.lower().split(';', 1)[0].strip()
        if normalized_mime in {'application/rss+xml','application/atom+xml',
                               'application/xml','text/xml'}:
            title, content, published_at = self.feed_content(text, final)
        elif normalized_mime in {'text/html','application/xhtml+xml'}:
            soup = BeautifulSoup(text, 'html.parser')
            title = soup.title.get_text(' ', strip=True)[:200] if soup.title else final
            published_at = self.published_date(soup)
            for tag in soup(['script', 'style', 'noscript', 'nav', 'footer']):
                tag.decompose()
            body = soup.find('article') or soup.find('main') or soup
            content = body.get_text(' ', strip=True)
        else:
            raise ToolFailure('unsupported_content')
        return dict(source_id=hashlib.sha256(final.encode()).hexdigest()[:24], url=final,
                    title=title, text=content[:30000], retrieved_at=now(), published_at=published_at,
                    content_hash=hashlib.sha256(content.encode()).hexdigest(), truncated=len(content)>30000,
                    status='ok', error=None)
