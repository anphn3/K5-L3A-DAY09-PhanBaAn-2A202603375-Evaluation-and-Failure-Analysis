"""Regression test for docs/trace_case.md: seeded_regression C-014@11.

First wrong step = event 5 `proposal` 120000 after `quote` 150000: the agent pre-deducted the
30000 already refunded (FM-05), the host subtracted it again, and the ledger holds 90000 instead
of 120000 while the reply says 120000 (FM-08). Run: python -m pytest -q -m student -o addopts= -k lab9
"""
import pytest

pytestmark = pytest.mark.student


@pytest.fixture(scope="module")
def case():
    from lab9.trace_case import investigate

    return investigate


def _ctx(trial, label):
    from pydantic_evals.evaluators import EvaluatorContext

    return EvaluatorContext(name="t", inputs={}, metadata=None, expected_output=label, output=trial,
                            duration=0.0, _span_tree=None, attributes={}, metrics={})


def test_lab9_trace_case_c014_first_wrong_step_is_pre_deducted_proposal(case):
    from lab9 import graders

    got = case("seeded_regression", "C-014", 11)
    trial, label = got["trial"], got["label"]
    kinds = [e["kind"] for e in trial["events"]]
    first = kinds.index("proposal")
    quote = next(e for e in trial["events"] if e["kind"] == "quote")["payload"]["amount_vnd"]
    assert kinds[first - 2:first] == ["quote", "refund_history"]
    assert quote == 150000 and trial["events"][first]["payload"]["amount_vnd"] == 120000
    assert trial["snapshot"]["refund_vnd"] == 90000 != label["refund_vnd"]
    ctx = _ctx(trial, label)
    assert graders.FullQuotePassed().evaluate(ctx).value is False        # catches the first wrong step
    assert graders.RefundAmountCorrect().evaluate(ctx).value is False    # catches the ledger outcome
    assert graders.ReplyMatchesLedger().evaluate(ctx).value is False     # catches the reply (FM-08)


def test_lab9_trace_case_c014_fixed_control_is_clean(case):
    from lab9 import graders

    got = case("fixed", "C-014", 11)
    trial, label = got["trial"], got["label"]
    assert "proposal" not in [e["kind"] for e in trial["events"]]
    assert trial["snapshot"]["refund_vnd"] == label["refund_vnd"] == 120000
    ctx = _ctx(trial, label)
    for g in (graders.FullQuotePassed, graders.RefundAmountCorrect, graders.ReplyMatchesLedger):
        assert g().evaluate(ctx).value is True
