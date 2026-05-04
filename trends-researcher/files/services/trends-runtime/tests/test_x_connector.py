from trend_harvester.services.connectors.x_trends import XTrendsConnector


def test_parse_nitter_explore_extracts_unique_terms():
    html = """
    <html><body>
      <a href="/search?q=OpenAI">OpenAI</a>
      <a href="/search?q=%23AI">#AI</a>
      <a href="/search?q=OpenAI">OpenAI</a>
      <a href="/search?q=help">help</a>
    </body></html>
    """
    rows = XTrendsConnector._parse_nitter_explore(html, limit=10)
    titles = [row["title"] for row in rows]
    assert "OpenAI" in titles
    assert "#AI" in titles
    assert titles.count("OpenAI") == 1
    assert "help" not in titles


def test_parse_trends24_extracts_trend_link_terms():
    html = """
    <div class=list-container>
      <ol class=trend-card__list>
        <li><span class=trend-name><a href="https://twitter.com/search?q=%23AI" class=trend-link>#AI</a></span></li>
        <li><span class=trend-name><a href="https://twitter.com/search?q=OpenAI" class=trend-link>OpenAI</a></span></li>
        <li><span class=trend-name><a href="https://twitter.com/search?q=OpenAI" class=trend-link>OpenAI</a></span></li>
      </ol>
    </div>
    """
    rows = XTrendsConnector._parse_trends24(html, limit=10)
    titles = [row["title"] for row in rows]
    assert "#AI" in titles
    assert "OpenAI" in titles
    assert titles.count("OpenAI") == 1
