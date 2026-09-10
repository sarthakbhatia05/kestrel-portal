import pytest

from kestrel.ask import resolver
from kestrel.ask.catalogue import Catalogue, RegionEntry
from kestrel.ask.gemini import LanguageUnavailable
from kestrel.ask.types import AskGrain, AskIntent, AskMetric, AskTurn


class FakeModel:
    """Records what it was asked and returns whatever it was told to."""

    def __init__(self, payload=None, raises=False):
        self.payload = payload
        self.raises = raises
        self.system = None
        self.prompt = None

    def generate_json(self, *, system, prompt, schema):
        self.system, self.prompt = system, prompt
        if self.raises:
            raise RuntimeError("transport failed")
        return self.payload

    def generate_text(self, *, system, prompt):  # pragma: no cover - unused here
        raise NotImplementedError


@pytest.fixture
def catalogue():
    return Catalogue(
        regions=[RegionEntry(region_id=1, region_name="West"),
                 RegionEntry(region_id=2, region_name="South")],
        warehouses=["West Hub"],
        categories=["Snacks"],
        return_reasons=["RT05_OVERSUPPLY"],
    )


def test_resolves_a_question_into_a_typed_intent(catalogue):
    model = FakeModel({"metric": "fill_rate", "grain": "outlet", "period": "FY27Q1",
                       "region_id": 1, "limit": 5, "ascending": True})
    intent = resolver.resolve(model, "worst 5 outlets for fill rate in West", catalogue)
    assert intent == AskIntent(
        metric=AskMetric.FILL_RATE, grain=AskGrain.OUTLET, period="FY27Q1",
        region_id=1, limit=5, ascending=True,
    )


def test_the_catalogue_reaches_the_model(catalogue):
    model = FakeModel({"metric": "otif"})
    resolver.resolve(model, "how is otif", catalogue)
    assert "West (region_id 1)" in model.system
    assert "RT05_OVERSUPPLY" in model.system


def test_the_window_reaches_the_model_without_any_figures(catalogue):
    model = FakeModel({"metric": "fill_rate", "region_id": 2})
    window = [AskTurn(question="fill rate last quarter",
                      intent=AskIntent(metric=AskMetric.FILL_RATE, grain=AskGrain.OUTLET))]
    resolver.resolve(model, "and South?", catalogue, window=window)
    assert "fill rate last quarter" in model.prompt
    assert "and South?" in model.prompt
    assert '"metric":"fill_rate"' in model.prompt


def test_an_unrecognised_question_is_declined(catalogue):
    model = FakeModel({"metric": "unsupported"})
    assert resolver.resolve(model, "who is on call tonight?", catalogue).metric is (
        AskMetric.UNSUPPORTED
    )


def test_a_malformed_response_is_declined_not_guessed(catalogue):
    model = FakeModel({"metric": "profit_margin", "grain": "outlet"})
    assert resolver.resolve(model, "margin by outlet", catalogue).metric is (
        AskMetric.UNSUPPORTED
    )


def test_a_transport_failure_is_reported_not_declined(catalogue):
    """An outage must not be dressed up as "the data cannot answer that"."""
    with pytest.raises(LanguageUnavailable):
        resolver.resolve(FakeModel(raises=True), "fill rate", catalogue)


def test_an_invented_region_is_declined(catalogue):
    model = FakeModel({"metric": "fill_rate", "region_id": 99})
    assert resolver.resolve(model, "fill rate in Atlantis", catalogue).metric is (
        AskMetric.UNSUPPORTED
    )


def test_dashboard_scope_fills_an_unstated_region(catalogue):
    model = FakeModel({"metric": "fill_rate"})
    intent = resolver.resolve(model, "how is fill rate", catalogue, scope_region_id=2)
    assert intent.region_id == 2


def test_a_region_named_in_the_question_beats_the_dashboard_scope(catalogue):
    model = FakeModel({"metric": "fill_rate", "region_id": 1})
    intent = resolver.resolve(model, "fill rate in West", catalogue, scope_region_id=2)
    assert intent.region_id == 1
