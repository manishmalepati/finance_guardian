from backend.receipts.gmail_sync import GmailSync


class PageResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class PageClient:
    def __init__(self, pages):
        self.pages = pages
        self.calls = 0

    def get(self, url, headers, params):
        assert "Bearer " in headers["Authorization"]
        assert params["q"].startswith("from:noreply@uber.com")
        page = self.pages[self.calls]
        self.calls += 1
        return PageResponse(page)


def test_targeted_discovery_follows_pages_and_deduplicates_ids():
    client = PageClient([
        {"messages": [{"id": "a"}, {"id": "b"}], "nextPageToken": "next"},
        {"messages": [{"id": "b"}, {"id": "c"}]},
    ])
    ids, limited = GmailSync(session=None, client=client)._message_ids("temporary-token")
    assert ids == ["a", "b", "c"]
    assert limited is False
    assert client.calls == 2


def test_discovery_reports_when_search_is_limited():
    client = PageClient([{"messages": [{"id": str(index)}], "nextPageToken": str(index)} for index in range(5)])
    ids, limited = GmailSync(session=None, client=client)._message_ids("temporary-token")
    assert len(ids) == 5
    assert limited is True
