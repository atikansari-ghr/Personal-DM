"""Dashboard widgets and other account preferences shared by every device (AT-65, AT-66, AT-78)."""
from conftest import client_for

from apps.core import registry
from apps.core.models import UserSetting


def _prefs(client):
    return client.get("/api/session").json()["preferences"]


def test_at65_widgets_are_a_list_of_real_widgets(family, clients):
    s = {d["key"]: d for d in clients["son1"].get("/api/settings").json()["settings"]}["me.dashboard_widgets"]
    assert s["type"] == "widget_list"
    assert s["choices"] == list(registry.WIDGETS)
    assert set(s["choice_labels"]) == set(registry.WIDGETS)  # human labels, no comma-separated ids to type
    assert s["value"] == registry.DEFAULT_WIDGETS  # new accounts start with the suggested widgets
    r = clients["son1"].put("/api/settings", {"values": {"me.dashboard_widgets": ["recent", "nonsense"]}}, format="json")
    assert r.status_code == 400
    assert _prefs(clients["son1"])["dashboard_widgets"] == registry.DEFAULT_WIDGETS


def test_at66_at78_order_persists_per_account_and_reaches_other_devices(family, clients):
    son1 = family["son1"]
    order = ["upcoming", "expiring", "recent", "documents", "upcoming"]
    r = clients["son1"].put("/api/settings", {"values": {"me.dashboard_widgets": order}}, format="json")
    assert r.status_code == 200, r.content
    phone = client_for(son1)  # a second device signed in to the same account
    assert _prefs(phone)["dashboard_widgets"] == ["upcoming", "expiring", "recent", "documents"]
    # other accounts are not affected
    assert _prefs(clients["son2"])["dashboard_widgets"] == registry.DEFAULT_WIDGETS
    # theme and layout follow the account too
    clients["son1"].put("/api/settings", {"values": {"me.theme": "blue", "me.layout": "full_page"}}, format="json")
    assert _prefs(phone)["theme"] == "blue" and _prefs(phone)["layout"] == "full_page"
    # empty selection is allowed (greeting only)
    clients["son1"].put("/api/settings", {"values": {"me.dashboard_widgets": []}}, format="json")
    assert _prefs(phone)["dashboard_widgets"] == []


def test_legacy_comma_separated_value_upgrades_without_changing_the_dashboard(family, clients):
    son1 = family["son1"]
    UserSetting.objects.update_or_create(user=son1, key="me.dashboard_widgets", defaults={"value": "documents,storage"})
    widgets = _prefs(clients["son1"])["dashboard_widgets"]
    assert widgets[:2] == ["documents", "storage"]
    # sections that were always shown before stay visible after the upgrade
    for w in ("review", "family", "saved_views", "recent", "upcoming", "review_queue", "backup"):
        assert w in widgets
    assert "members" not in widgets and "expiring" not in widgets
