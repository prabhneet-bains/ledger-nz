from uuid import UUID


def match_account(description: str, rules: list[dict]) -> UUID | None:
    """Longest keyword wins; then lowest priority number."""
    text = (description or "").upper()
    ranked: list[tuple[int, int, UUID]] = []
    for rule in rules:
        keyword = (rule.get("keyword") or "").upper()
        if not keyword or keyword not in text:
            continue
        ranked.append((len(keyword), -int(rule.get("priority") or 100), UUID(rule["account_id"])))
    if not ranked:
        return None
    ranked.sort(reverse=True)
    return ranked[0][2]


def uncategorised_id(accounts: list[dict]) -> UUID | None:
    for account in accounts:
        if account.get("account_name") == "Uncategorised Expense":
            return UUID(account["account_id"])
    return None


def account_name_to_id(accounts: list[dict], name: str) -> UUID | None:
    needle = (name or "").strip().lower()
    for account in accounts:
        if account["account_name"].lower() == needle:
            return UUID(account["account_id"])
    for account in accounts:
        if needle and needle in account["account_name"].lower():
            return UUID(account["account_id"])
    return None
