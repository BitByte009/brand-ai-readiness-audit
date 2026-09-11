"""Local explicit-span probe. Unknown answers are not evidence of missing facts."""
import hashlib
import re
from bs4 import BeautifulSoup
from lib.common.extract import extract_text, language_supported
from lib.common.observations import make_observation


def detect_capability():
    return {'available': True, 'method': 'deterministic_explicit_spans', 'negative_inference': False}


def run_probe(pages, capability=None):
    if capability is not None and not capability.get('available'):
        return {'observations': [], 'coverage': [{'check_id': 'X-COV-01', 'status': 'skipped',
                'reason': 'PROBE_UNAVAILABLE', 'detail': capability.get('reason', ''), 'scope': 'extraction probe'}]}
    observations = []
    for page in pages:
        html, url = page['html'], page['url']
        text = extract_text(html)
        soup = BeautifulSoup(html, 'html.parser')
        questions = []
        def answer(qid, label, span):
            span = re.sub(r'\s+', ' ', span or '').strip()
            if span and span in text:
                questions.append({'id': qid, 'question': label, 'category': 'factual',
                    'answered': True, 'relevant': qid == 'Q6', 'answer': span, 'evidence_span': span,
                    'expects_explicit_statement': False})
        for match in re.finditer(r'(?:[$€£₹]\s*\d[\d,.]*|\b\d[\d,.]*\s*(?:USD|EUR|GBP|INR)\b)', text):
            answer('Q6', 'What price is explicitly stated?', match.group())
            break
        if language_supported(html):
            main = soup.find('main') or soup.find('article') or soup.body or soup
            for paragraph in main.find_all('p'):
                span = paragraph.get_text(' ', strip=True)
                if len(span) >= 30 and re.search(r'\b(is|are|costs|opens|closes|includes|provides)\b', span, re.I):
                    answer('Q5', 'What explicit statement does the page provide?', span)
                    break
        observations.append(make_observation('PROBE', url, {'questions': questions,
            'source_text_hash': hashlib.sha256(text.encode()).hexdigest(),
            'method': 'deterministic_explicit_spans', 'negative_inference': False,
            'lens': page.get('lens', 'raw')}))
    return {'observations': observations, 'coverage': []}
