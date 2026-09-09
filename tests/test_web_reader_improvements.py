import asyncio

from bs4 import BeautifulSoup

from app.agent.web import WebReader


def test_extracts_publication_date_from_common_html_metadata():
    for markup, expected in [
        ('<meta name="date" content="2026-09-09">', '2026-09-09'),
        ('<time datetime="2026-09-08T10:00:00Z"></time>', '2026-09-08T10:00:00Z'),
        ('<script type="application/ld+json">'
         '{"datePublished":"2026-09-07"}</script>', '2026-09-07'),
    ]:
        assert WebReader.published_date(BeautifulSoup(markup, 'html.parser')) == expected


def test_reads_rss_and_atom_without_external_parser():
    rss = '''<?xml version="1.0"?><rss><channel><title>Versions</title>
      <item><title>Version 2</title><description><![CDATA[<p>Nouveau moteur.</p>]]></description>
      <pubDate>Wed, 09 Sep 2026 10:00:00 GMT</pubDate></item></channel></rss>'''
    title, content, published = WebReader.feed_content(rss, 'https://example.com/feed')
    assert title == 'Versions'
    assert content == 'Version 2 — Nouveau moteur.'
    assert published.startswith('Wed, 09 Sep 2026')


def test_document_redirect_is_checked_against_domains_and_robots():
    class Reader(WebReader):
        def __init__(self):
            super().__init__(lambda: None)
            self.allowed = []

        async def ensure_allowed(self, url, domains):
            self.allowed.append(url)

        async def request(self, url, domains, follow_redirects=False,
                          before_redirect=None):
            assert follow_redirects
            target = 'https://example.com/releases/current'
            await before_redirect(target)
            return target, 200, 'text/html; charset=utf-8', (
                '<html><head><meta itemprop="datePublished" content="2026-09-09">'
                '<title>Version</title></head><main>Nouveau moteur documenté.</main></html>')

    async def run():
        reader = Reader()
        page = await reader.read('https://example.com/latest', ['example.com'])
        assert reader.allowed == ['https://example.com/latest',
                                  'https://example.com/releases/current']
        assert page['url'].endswith('/releases/current')
        assert page['published_at'] == '2026-09-09'
        assert page['text'] == 'Nouveau moteur documenté.'
    asyncio.run(run())
