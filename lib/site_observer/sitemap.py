"""Bounded sitemap discovery through the anonymous robots-aware transport."""
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree


def discover(origin, robots, fetch, *, time_left=lambda: 1):
    queue = list(dict.fromkeys(robots.get('document', {}).get('sitemap', []) or [urljoin(origin, '/sitemap.xml')]))[:3]
    visited, urls, statuses = set(), set(), []
    truncated = False
    while queue and len(visited) < 3 and time_left() > 0:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        response = fetch(url)
        code = response.get('status_code')
        if code != 200:
            statuses.append('missing' if code == 404 else 'error')
            continue
        text = response.get('html', '')
        if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper():
            statuses.append('error')
            continue
        try:
            document = ElementTree.fromstring(text)
        except (ElementTree.ParseError, ValueError):
            statuses.append('error')
            continue
        kind = document.tag.rsplit('}', 1)[-1]
        if kind not in {'sitemapindex', 'urlset'}:
            statuses.append('error')
            continue
        statuses.append('ok')
        for node in document.iter():
            if node.tag.rsplit('}', 1)[-1] != 'loc' or not node.text:
                continue
            target = node.text.strip()
            try:
                parsed = urlsplit(target)
            except ValueError:
                continue
            if parsed.scheme not in {'http', 'https'} or parsed.netloc != urlsplit(origin).netloc:
                continue
            if kind == 'sitemapindex':
                if len(queue) < 3:
                    queue.append(target)
                else:
                    truncated = True
            elif len(urls) < 180:
                urls.add(target)
            elif target not in urls:
                truncated = True
    status = 'ok' if 'ok' in statuses else 'missing' if statuses and all(s == 'missing' for s in statuses) else 'error'
    return {'status': status, 'entries': [{'loc': u} for u in sorted(urls)],
            'checked_urls': sorted(visited), 'partial': truncated or bool(queue) or 'error' in statuses}
