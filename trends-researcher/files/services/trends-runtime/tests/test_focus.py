from trend_harvester.schemas import RunStartRequest
from trend_harvester.services.focus import focus_relevance_score, is_low_signal_title


def test_focus_query_alias_query_field_is_accepted():
    req = RunStartRequest.model_validate({"query": "english premier league"})
    assert req.focus_query == "english premier league"


def test_focus_relevance_for_epl_title_is_high():
    score = focus_relevance_score("Arsenal vs Liverpool: Premier League title race update", "english premier league")
    assert score >= 0.2


def test_low_signal_titles_are_filtered():
    assert is_low_signal_title("#oc")
    assert is_low_signal_title("This is the best feeling ever #relatablestories #comedy #funnymemes")
    assert not is_low_signal_title("Premier League transfer update: Chelsea targets new striker")
