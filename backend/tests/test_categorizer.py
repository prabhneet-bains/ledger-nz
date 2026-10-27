from app.services.categorizer import match_account


def test_longest_keyword_wins():
    rules = [
        {"keyword": "BP", "account_id": "00000000-0000-0000-0000-000000000001", "priority": 50},
        {"keyword": "BP CONNECT", "account_id": "00000000-0000-0000-0000-000000000002", "priority": 50},
    ]
    matched = match_account("BP CONNECT ROTORUA", rules)
    assert str(matched) == "00000000-0000-0000-0000-000000000002"
