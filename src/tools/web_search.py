import urllib.request
import urllib.parse
import re
import html
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)

def _search_bing(query: str, max_results: int = 4) -> List[Dict[str, str]]:
    """Searches Bing and extracts clean titles, snippets, and URLs."""
    results = []
    try:
        encoded = urllib.parse.quote(query)
        url = f"https://www.bing.com/search?q={encoded}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as resp:
            content = resp.read().decode("utf-8", errors="ignore")

        # Parse with lxml if available, otherwise regex
        try:
            from lxml import html as lxml_html
            tree = lxml_html.fromstring(content)
            items = tree.xpath('//li[contains(@class, "b_algo")]')
            for item in items[:max_results]:
                h2 = item.xpath('.//h2')
                title = h2[0].text_content().strip() if h2 else ""
                p = item.xpath('.//p')
                snippet = p[0].text_content().strip() if p else ""
                links = item.xpath('.//a/@href')
                link = links[0] if links else ""
                if title or snippet:
                    results.append({
                        "title": title,
                        "snippet": snippet,
                        "url": link
                    })
        except Exception as parse_err:
            logger.debug(f"[WebSearch] lxml parsing fallback to regex: {parse_err}")
            # Regex extraction for b_algo
            blocks = re.findall(r'<li class="b_algo".*?>(.*?)</li>', content, flags=re.DOTALL)
            for b in blocks[:max_results]:
                t_match = re.search(r'<h2><a[^>]*>(.*?)</a></h2>', b, flags=re.DOTALL)
                title = re.sub(r'<[^>]+>', '', t_match.group(1)) if t_match else ""
                s_match = re.search(r'<p[^>]*>(.*?)</p>', b, flags=re.DOTALL)
                snippet = re.sub(r'<[^>]+>', '', s_match.group(1)) if s_match else ""
                if title or snippet:
                    results.append({
                        "title": html.unescape(title).strip(),
                        "snippet": html.unescape(snippet).strip(),
                        "url": ""
                    })
    except Exception as e:
        logger.warning(f"[WebSearch] Bing search failed: {e}")
    return results

def _search_wikipedia(query: str) -> List[Dict[str, str]]:
    """Wikipedia API fallback for informational queries."""
    results = []
    try:
        encoded = urllib.parse.quote(query)
        url = f"https://ru.wikipedia.org/w/api.php?action=query&list=search&srsearch={encoded}&format=json&utf8=1&srlimit=2"
        req = urllib.request.Request(url, headers={"User-Agent": "BomzhAssistant/2.0"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            import json
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            items = data.get("query", {}).get("search", [])
            for item in items:
                title = item.get("title", "")
                snippet = re.sub(r'<[^>]+>', '', item.get("snippet", ""))
                snippet = html.unescape(snippet).strip()
                results.append({
                    "title": f"Википедия: {title}",
                    "snippet": snippet,
                    "url": f"https://ru.wikipedia.org/wiki/{urllib.parse.quote(title)}"
                })
    except Exception as e:
        logger.warning(f"[WebSearch] Wikipedia fallback failed: {e}")
    return results

def search_web(query: str, max_results: int = 4) -> str:
    """Выполняет поиск актуальной информации в интернете через поисковую систему.
    Используй этот инструмент, когда пользователь спрашивает о текущих событиях,
    курсах валют, погоде, расписании, свежих новостях или фактах, требующих актуальных данных из сети.
    
    Args:
        query: Поисковый запрос на русском или английском языке.
        max_results: Максимальное количество результатов (по умолчанию 4).
    Returns:
        Сводка найденной информации со сниппетами из поисковой выдачи.
    """
    clean_query = query.strip()
    if not clean_query:
        return "⚠️ Поисковый запрос пуст."

    logger.info(f"[WebSearch] Searching web for: '{clean_query}'")

    # 1. Primary: Bing Search
    items = _search_bing(clean_query, max_results=max_results)

    # 2. Fallback: Wikipedia API if no results
    if not items:
        logger.info(f"[WebSearch] Bing had 0 results, querying Wikipedia fallback for '{clean_query}'...")
        items = _search_wikipedia(clean_query)

    if not items:
        return f"По запросу '{clean_query}' ничего не найдено в интернете. Попробуйте уточнить формулировку."

    formatted = [f"🔍 Результаты поиска в сети по запросу «{clean_query}»:\n"]
    for i, it in enumerate(items[:max_results], 1):
        t = it.get("title", "")
        s = it.get("snippet", "")
        u = it.get("url", "")
        source_line = f" [Ссылка: {u}]" if u else ""
        formatted.append(f"{i}. **{t}**\n   {s}{source_line}")

    return "\n\n".join(formatted)
