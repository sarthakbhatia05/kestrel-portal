import sqlite3

import pytest
from fastapi.testclient import TestClient

from kestrel.ask.router import get_language_model
from kestrel.dependencies import get_curated_db
from kestrel.main import create_app
from kestrel.transform.runner import build
from kestrel.transform.steps import (
    s00_reference,
    s20_orders,
    s30_deliveries,
    s40_returns,
    s50_inventory,
)


class FakeModel:
    """Returns a canned intent and a canned narration."""

    def __init__(self, intent, prose="Fill rate held broadly steady."):
        self.intent = intent
        self.prose = prose

    def generate_json(self, *, system, prompt, schema):
        if isinstance(self.intent, Exception):
            raise self.intent
        return self.intent

    def generate_text(self, *, system, prompt):
        return self.prose


@pytest.fixture
def make_client(tmp_path, source_db):
    curated = tmp_path / "curated.db"
    build(
        source_db, curated,
        steps=[s00_reference, s20_orders, s30_deliveries, s40_returns, s50_inventory],
    )

    def _override_db():
        conn = sqlite3.connect(curated)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _make(model):
        app = create_app()
        app.dependency_overrides[get_curated_db] = _override_db
        app.dependency_overrides[get_language_model] = lambda: model
        return TestClient(app)

    return _make


def test_a_question_is_answered_with_a_figure_and_its_basis(make_client):
    client = make_client(
        FakeModel({"metric": "fill_rate", "grain": "outlet", "period": "FY27Q1"})
    )
    response = client.post("/api/service/ask", json={"question": "How is fill rate?"})
    assert response.status_code == 200
    body = response.json()
    assert body["declined"] is False
    assert "Fill rate was" in body["answer"]
    assert body["result"]["basis"]["period_label"] == "FY27 Q1"
    assert body["intent"]["metric"] == "fill_rate"


def test_supporting_figures_come_back_alongside_the_prose(make_client):
    client = make_client(
        FakeModel({"metric": "fill_rate", "grain": "outlet", "period": "FY27Q1"})
    )
    body = client.post("/api/service/ask", json={"question": "fill rate?"}).json()
    assert body["result"]["rows"]
    assert body["result"]["numerator"] > 0


def test_an_unsupported_question_is_declined_naming_what_is_supported(make_client):
    client = make_client(FakeModel({"metric": "unsupported"}))
    body = client.post(
        "/api/service/ask", json={"question": "Will demand rise next quarter?"}
    ).json()
    assert body["declined"] is True
    assert body["result"] is None
    assert "cannot answer" in body["answer"]
    assert any("fill rate" in m for m in body["supported_metrics"])


def test_a_grain_the_metric_cannot_serve_is_declined(make_client):
    client = make_client(FakeModel({"metric": "returns", "grain": "outlet"}))
    body = client.post("/api/service/ask", json={"question": "returns by outlet?"}).json()
    assert body["declined"] is True


def test_prose_that_invents_a_figure_is_dropped_not_returned(make_client):
    client = make_client(
        FakeModel(
            {"metric": "fill_rate", "grain": "outlet", "period": "FY27Q1"},
            prose="Fill rate came in at 87.5%, well below plan.",
        )
    )
    body = client.post("/api/service/ask", json={"question": "fill rate?"}).json()
    assert body["prose"] is None
    assert "Fill rate was" in body["answer"]


def test_prose_is_kept_when_every_figure_checks_out(make_client):
    client = make_client(
        FakeModel({"metric": "fill_rate", "grain": "outlet", "period": "FY27Q1"})
    )
    body = client.post("/api/service/ask", json={"question": "fill rate?"}).json()
    assert body["prose"] == "Fill rate held broadly steady."


def test_the_selected_scope_reaches_the_answer(make_client):
    client = make_client(
        FakeModel({"metric": "fill_rate", "grain": "outlet", "period": "FY27Q1"})
    )
    body = client.post(
        "/api/service/ask", json={"question": "fill rate?", "region_id": 1}
    ).json()
    assert body["intent"]["region_id"] == 1
    assert body["result"]["basis"]["scope"] != "National"


def test_the_window_is_accepted_and_capped(make_client):
    client = make_client(
        FakeModel({"metric": "fill_rate", "grain": "outlet", "period": "FY27Q1"})
    )
    turn = {"question": "fill rate?", "intent": {"metric": "fill_rate"}}
    assert client.post(
        "/api/service/ask", json={"question": "and South?", "window": [turn] * 10}
    ).status_code == 200
    assert client.post(
        "/api/service/ask", json={"question": "and South?", "window": [turn] * 11}
    ).status_code == 422


def test_the_dashboard_keeps_working_when_the_capability_is_absent(make_client):
    client = make_client(None)
    assert client.post("/api/service/ask", json={"question": "fill rate?"}).status_code == 503
    assert client.get(
        "/api/service/fill-rate", params={"grain": "outlet", "period": "FY27Q1"}
    ).status_code == 200


def test_capability_reports_availability(make_client):
    absent = make_client(None).get("/api/service/ask/capability").json()
    assert absent["available"] is False
    assert absent["supported_metrics"]
    present = make_client(FakeModel({"metric": "otif"})).get(
        "/api/service/ask/capability"
    ).json()
    assert present["available"] is True


def test_an_unreachable_model_is_an_outage_not_a_decline(make_client):
    """503, not a 200 decline: the question was never read, so claiming the
    data cannot answer it would be a statement we have not earned."""
    client = make_client(FakeModel(RuntimeError("connection reset")))
    response = client.post("/api/service/ask", json={"question": "fill rate?"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ASK_UNAVAILABLE"


class SequencedModel:
    """Returns each scripted JSON payload in turn.

    An investigation makes one call to resolve the question and one per
    step, so a single canned payload is not enough to drive it.
    """

    def __init__(self, payloads, prose="Fill rate fell in the West."):
        self.payloads = list(payloads)
        self.prose = prose

    def generate_json(self, *, system, prompt, schema):
        return self.payloads.pop(0) if self.payloads else {"done": True}

    def generate_text(self, *, system, prompt):
        return self.prose


INVESTIGATE = {"metric": "fill_rate", "grain": "outlet", "period": "FY27Q1",
               "region_id": 1, "mode": "investigate"}
STEP_Q1 = {"reasoning": "Fill rate for the quarter.",
           "intent": {"metric": "fill_rate", "grain": "outlet", "period": "FY27Q1"}}
STEP_Q4 = {"reasoning": "The quarter before, to compare.",
           "intent": {"metric": "fill_rate", "grain": "outlet", "period": "FY26Q4"}}


def test_an_investigation_returns_the_steps_it_ran(make_client):
    """The honesty surface: what produced this answer is visible."""
    client = make_client(SequencedModel([INVESTIGATE, STEP_Q1, STEP_Q4, {"done": True}]))
    body = client.post("/api/service/ask", json={"question": "why did fill rate drop?"}).json()
    assert [step["reasoning"] for step in body["steps"]] == [
        "Fill rate for the quarter.",
        "The quarter before, to compare.",
    ]


def test_an_investigation_states_every_measurement_in_the_answer_of_record(make_client):
    client = make_client(SequencedModel([INVESTIGATE, STEP_Q1, STEP_Q4, {"done": True}]))
    body = client.post("/api/service/ask", json={"question": "why did fill rate drop?"}).json()
    assert "FY27 Q1" in body["answer"]
    assert "FY26 Q4" in body["answer"]
    assert body["declined"] is False


def test_a_lookup_still_answers_in_one_step_with_no_trail(make_client):
    """The path that already existed is untouched by the loop."""
    client = make_client(FakeModel({"metric": "fill_rate", "grain": "outlet",
                                    "period": "FY27Q1"}))
    body = client.post("/api/service/ask", json={"question": "how is fill rate?"}).json()
    assert body["steps"] is None
    assert body["result"] is not None


def test_the_dashboards_period_reaches_ask_anything(make_client):
    """C5.3: one scope, applied to every surface -- period as well as region."""
    client = make_client(FakeModel({"metric": "fill_rate", "grain": "outlet",
                                    "period": "latest"}))
    body = client.post(
        "/api/service/ask", json={"question": "how is fill rate?", "period": "FY26Q4"}
    ).json()
    assert body["result"]["basis"]["period_label"] == "FY26 Q4"


def test_a_period_named_in_the_question_still_beats_the_dashboard(make_client):
    client = make_client(FakeModel({"metric": "fill_rate", "grain": "outlet",
                                    "period": "FY27Q1"}))
    body = client.post(
        "/api/service/ask", json={"question": "fill rate in FY27 Q1?", "period": "FY26Q4"}
    ).json()
    assert body["result"]["basis"]["period_label"] == "FY27 Q1"


def test_an_investigation_that_measures_nothing_declines(make_client):
    """No measurement means no answer -- not a paragraph of prose (C4.4)."""
    impossible = {"reasoning": "Returns by outlet.",
                  "intent": {"metric": "returns", "grain": "outlet", "period": "FY27Q1"}}
    client = make_client(SequencedModel([INVESTIGATE, impossible, {"done": True}]))
    body = client.post("/api/service/ask", json={"question": "why?"}).json()
    assert body["declined"] is True
    assert body["prose"] is None


def _events(client, payload):
    """Parse an SSE response into the JSON objects it carried."""
    import json

    with client.stream("POST", "/api/service/ask/stream", json=payload) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        return [
            json.loads(line[len("data: "):])
            for line in response.iter_lines()
            if line.startswith("data: ")
        ]


def test_streaming_emits_each_step_before_the_answer(make_client):
    """A six-step investigation is ten seconds of silence otherwise."""
    client = make_client(SequencedModel([INVESTIGATE, STEP_Q1, STEP_Q4, {"done": True}]))
    events = _events(client, {"question": "why did fill rate drop?"})
    assert [event["type"] for event in events] == ["step", "step", "answer"]
    assert events[0]["reasoning"] == "Fill rate for the quarter."


def test_streaming_answer_event_carries_the_whole_answer(make_client):
    client = make_client(SequencedModel([INVESTIGATE, STEP_Q1, STEP_Q4, {"done": True}]))
    events = _events(client, {"question": "why did fill rate drop?"})
    answer = events[-1]
    assert "FY27 Q1" in answer["answer"]
    assert len(answer["steps"]) == 2


def test_streaming_a_lookup_emits_no_steps_only_an_answer(make_client):
    client = make_client(FakeModel({"metric": "fill_rate", "grain": "outlet",
                                    "period": "FY27Q1"}))
    events = _events(client, {"question": "how is fill rate?"})
    assert [event["type"] for event in events] == ["answer"]
    assert events[0]["result"] is not None


def test_streaming_a_declined_question_says_so_in_the_answer_event(make_client):
    client = make_client(FakeModel({"metric": "unsupported"}))
    events = _events(client, {"question": "what is our headcount?"})
    assert events[-1]["declined"] is True
