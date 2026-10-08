from backend.services.categorization import MerchantNormalizer, _extract_json


def test_normalizer_removes_statement_noise():
    normalizer = MerchantNormalizer()

    assert normalizer.normalize("UBER *EATS HELP.UBER.COM CA") == "uber eats uber"
    assert normalizer.normalize("DOORDASH*09/20-2 ORDER 855-431-0459 CA") == "doordash"


def test_extract_json_accepts_fenced_response():
    payload = _extract_json(
        """```json
        {"results": [{"normalized_merchant": "uber eats", "category_id": "food_delivery"}]}
        ```"""
    )

    assert payload["results"][0]["category_id"] == "food_delivery"
