"""AT-19: personal IMAP accounts/rules — writable destinations, idempotent polls, private credentials.

Uses an in-memory IMAP double implementing the subset of imaplib used by the importer. A test against a
real mailbox server is listed as pending in docs/TEST_REPORT.md.
"""
from email.message import EmailMessage

import pytest
from conftest import client_for, make_text_pdf, personal_root

from apps.library.models import AccessRule, Document, Folder
from apps.mailimport import imap
from apps.mailimport.models import EmailAccount, ImportedAttachment

pytestmark = pytest.mark.django_db


def _msg(sender, subject, attachments):
    m = EmailMessage()
    m["From"], m["Subject"] = sender, subject
    m.set_content("synthetic body")
    for name, data in attachments:
        m.add_attachment(data, maintype="application", subtype="pdf", filename=name)
    return m.as_bytes()


class FakeImap:
    def __init__(self, messages, uidvalidity=b"777"):
        self.messages = messages  # uid -> bytes
        self.untagged_responses = {"UIDVALIDITY": [uidvalidity]}
        self.flags_changed = False

    def select(self, mailbox, readonly=False):
        assert readonly is True  # never modifies the mailbox
        return "OK", [b"1"]

    def uid(self, cmd, *args):
        if cmd == "search":
            lo = int(args[1].split()[1].split(":")[0])
            return "OK", [b" ".join(str(u).encode() for u in sorted(self.messages) if u >= lo)]
        if cmd == "fetch":
            assert "PEEK" in args[1]
            return "OK", [(b"1 (BODY[] {n}", self.messages[int(args[0])])]
        raise AssertionError(cmd)

    def logout(self):
        pass


def _account(user, folder, **rule):
    from apps.core import crypto

    acc = EmailAccount.objects.create(user=user, label="Mail", host="imap.invalid", username="u",
                                      password_enc=crypto.encrypt("synthetic-imap-pw"))
    acc.rules.create(name="Bank", destination=folder, sender_contains=rule.get("sender", "bank"), extensions="pdf")
    return acc


def test_poll_imports_matching_attachments_idempotently(family):
    son1 = family["son1"]
    folder = Folder.objects.create(parent=personal_root(son1), name="Banking", owner=son1)
    acc = _account(son1, folder)
    fake = FakeImap({
        1: _msg("statements@bank.example", "Statement", [("st.pdf", make_text_pdf("statement"))]),
        2: _msg("friend@example.invalid", "Hi", [("x.pdf", make_text_pdf("ignored"))]),
        3: _msg("alerts@bank.example", "Two files", [("a.pdf", make_text_pdf("a")), ("a.pdf", make_text_pdf("a"))]),
    })
    res = imap.poll_account(acc, conn=fake)
    assert res["imported"] == 3
    assert Document.objects.filter(folder=folder).count() == 3  # identical attachments stay separate
    again = imap.poll_account(acc, conn=fake)
    assert again["imported"] == 0 and Document.objects.filter(folder=folder).count() == 3
    acc.refresh_from_db()
    acc.last_uid = 0  # even re-scanning from the start does not duplicate
    acc.save()
    imap.poll_account(acc, conn=fake)
    assert Document.objects.filter(folder=folder).count() == 3
    assert Document.objects.filter(source_path__startswith="email:").count() == 3


def test_permission_rechecked_each_poll_and_failed_parts_retried(family):
    son1 = family["son1"]
    folder = Folder.objects.create(parent=personal_root(son1), name="Inbox docs", owner=son1)
    acc = _account(son1, folder)
    fake = FakeImap({1: _msg("bank@bank.example", "S", [("s.pdf", make_text_pdf("s"))])})
    AccessRule.objects.filter(user=son1).update(caps=1)  # upload removed
    imap.poll_account(acc, conn=fake)
    assert not Document.objects.filter(folder=folder).exists()
    assert ImportedAttachment.objects.get().status == "failed"
    acc.refresh_from_db()
    assert acc.last_uid == 0  # message with a failed part is retried later
    AccessRule.objects.filter(user=son1).update(caps=127)
    imap.poll_account(acc, conn=fake)
    assert Document.objects.filter(folder=folder).count() == 1


def test_rules_only_target_writable_folders_and_credentials_stay_private(family, clients):
    son1 = family["son1"]
    r = clients["son1"].post("/api/me/email-accounts", {"label": "Mail", "host": "imap.invalid", "username": "u",
                                                        "password": "synthetic-imap-pw"}, format="json")
    assert r.status_code == 201 and "synthetic-imap-pw" not in r.content.decode()
    aid = r.json()["id"]
    other = personal_root(family["son2"])
    r = clients["son1"].post(f"/api/me/email-accounts/{aid}/rules", {"name": "x", "destination": str(other.id)}, format="json")
    assert r.status_code == 400
    r = clients["son1"].post(f"/api/me/email-accounts/{aid}/rules", {"name": "x", "destination": str(personal_root(son1).id)}, format="json")
    assert r.status_code == 200
    # other users cannot see or use the account; admin sees only metadata
    assert clients["mom"].get("/api/me/email-accounts").json()["accounts"] == []
    assert clients["mom"].patch(f"/api/me/email-accounts/{aid}", {"label": "y"}, format="json").status_code == 404
    admin_view = clients["dad"].get("/api/admin/email-connectors").content.decode()
    assert "synthetic-imap-pw" not in admin_view and "password" not in admin_view
    clients["dad"].post("/api/admin/email-connectors", {"id": aid, "disabled": True}, format="json")
    assert imap.poll_account(EmailAccount.objects.get(pk=aid)) == {"skipped": True}
