import json

import httpx
import pytest
from openai import OpenAI

from openings_research.review import OpenAIReviewer, ReviewDecision, ReviewOutput, validate_reviews


def candidate(candidate_id="a", kind="claim"):
    return {
        "candidate_id": candidate_id,
        "kind": kind,
        "payload_json": json.dumps(
            {
                "text": "The bishop sacrifice is speculative.",
                "category": "pawn_break",
                "side": "white",
                "position_fen": None,
                "evidence": [
                    {
                        "source_version_id": "s",
                        "excerpt": "A speculative bishop sacrifice.",
                        "relation": "supports",
                    }
                ],
            }
        ),
    }


def decision(candidate_id="a", category="assessment"):
    return ReviewDecision(
        candidate_id=candidate_id,
        decision="accept",
        category=category,
        rationale="This assesses a sacrifice; no pawn advance is described.",
    )


@pytest.mark.parametrize("reviews", [[], [decision("unknown")], [decision(), decision()]])
def test_review_must_cover_exact_candidate_set(reviews):
    with pytest.raises(ValueError, match="exactly once"):
        validate_reviews(ReviewOutput(reviews=reviews), [candidate()])


def test_accepted_claim_needs_category_and_line_must_not_have_one():
    with pytest.raises(ValueError, match="category"):
        validate_reviews(ReviewOutput(reviews=[decision(category=None)]), [candidate()])
    with pytest.raises(ValueError, match="category"):
        validate_reviews(ReviewOutput(reviews=[decision()]), [candidate(kind="line")])


def response_with(output):
    return httpx.Response(
        200,
        json={
            "id": "resp_review",
            "created_at": 0,
            "model": "gpt-5.4-mini",
            "object": "response",
            "status": "completed",
            "output": [
                {
                    "id": "msg_review",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": json.dumps(output), "annotations": []}],
                }
            ],
            "usage": {"input_tokens": 50, "output_tokens": 20, "total_tokens": 70},
        },
    )


def run_review(handler, candidates):
    reviewer = OpenAIReviewer("test-key", "gpt-5.4-mini")
    reviewer.client.close()
    with OpenAI(api_key="test-key", http_client=httpx.Client(transport=httpx.MockTransport(handler))) as client:
        reviewer.client = client
        return reviewer.review("Italian Game", candidates, {"s": "fixture://s"})


def test_schema_keys_every_candidate_and_types_categories_by_kind():
    seen = {}

    def handler(request):
        seen["schema"] = json.loads(request.content)["text"]["format"]["schema"]
        return response_with({
            "claims": {
                "c0001": {"decision": "reject", "category": "plan", "rationale": "Not supported by the passage."},
                "c0002": {"decision": "accept", "category": "tactic", "rationale": "The passage shows the trick."},
            },
            "lines": {"c0003": {"decision": "accept", "rationale": "The source gives the full sequence."}},
        })

    candidates = [candidate("claim-a"), candidate("claim-b"), candidate("line-c", kind="line")]
    result = run_review(handler, candidates)
    schema = seen["schema"]
    defs = schema["$defs"]

    def resolve(node):
        return defs[node["$ref"].split("/")[-1]] if "$ref" in node else node

    claims, lines = resolve(schema["properties"]["claims"]), resolve(schema["properties"]["lines"])
    # Exactly one decision per candidate: every alias is a required key and no others are allowed.
    assert sorted(claims["required"]) == sorted(claims["properties"]) == ["c0001", "c0002"]
    assert lines["required"] == list(lines["properties"]) == ["c0003"]
    assert claims["additionalProperties"] is False and lines["additionalProperties"] is False
    claim, line = resolve(claims["properties"]["c0001"]), resolve(lines["properties"]["c0003"])
    assert "category" in claim["required"] and "null" not in json.dumps(claim["properties"]["category"])
    assert "category" not in line["properties"]
    by_id = {r.candidate_id: r for r in result.output.reviews}
    assert by_id["claim-a"].category == "plan" and by_id["line-c"].category is None
    validate_reviews(result.output, candidates)


def test_a_batch_without_lines_omits_the_lines_object():
    seen = {}

    def handler(request):
        seen["schema"] = json.loads(request.content)["text"]["format"]["schema"]
        return response_with({"claims": {"c0001": decision("c0001").model_dump(exclude={"candidate_id"})}})

    run_review(handler, [candidate("only-claim")])
    assert list(seen["schema"]["properties"]) == ["claims"]


def test_openai_review_preserves_wire_output_and_restores_candidate_ids():
    def handler(request):
        body = json.loads(request.content)
        context = json.loads(body["input"][1]["content"])
        assert context["candidates"][0]["candidate_id"] == "c0001"
        assert context["candidates"][0]["candidate"]["category"] == "pawn_break"
        assert "piece sacrifice is not a pawn break" in body["input"][0]["content"]
        output = json.dumps({"claims": {"c0001": decision("c0001").model_dump(exclude={"candidate_id"})}})
        return httpx.Response(
            200,
            json={
                "id": "resp_review",
                "created_at": 0,
                "model": "gpt-4.1-mini",
                "object": "response",
                "status": "completed",
                "output": [
                    {
                        "id": "msg_review",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": output, "annotations": []}],
                    }
                ],
                "usage": {"input_tokens": 50, "output_tokens": 20, "total_tokens": 70},
            },
        )

    reviewer = OpenAIReviewer("test-key", "gpt-4.1-mini")
    reviewer.client.close()
    with OpenAI(
        api_key="test-key", http_client=httpx.Client(transport=httpx.MockTransport(handler))
    ) as client:
        reviewer.client = client
        result = reviewer.review("Italian Game", [candidate("original-id")], {"s": "fixture://s"})
    assert result.output.reviews[0].candidate_id == "original-id"
    assert result.output.reviews[0].category == "assessment"
    assert json.loads(result.raw_response)["candidate_aliases"] == {"c0001": "original-id"}
    validate_reviews(result.output, [candidate("original-id")])


def test_prompts_keep_research_within_the_requested_opening():
    from openings_research.agents import SYSTEM_PROMPT
    from openings_research.review import REVIEW_PROMPT

    assert "Stay within the requested opening" in SYSTEM_PROMPT
    assert "Every candidate must belong to the requested opening" in REVIEW_PROMPT
    assert "transpositions count" in SYSTEM_PROMPT and "transpositions count" in REVIEW_PROMPT
