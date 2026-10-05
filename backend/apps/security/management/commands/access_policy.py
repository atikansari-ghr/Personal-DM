"""Console recovery for the geographic / IP access policy (requires shell access on the server).

  personaldocs access-policy status
  personaldocs access-policy off              # disable country filtering (rules are kept)
  personaldocs access-policy rollback         # restore the policy before the last change
  personaldocs access-policy trust-ip 203.0.113.7 [--hours 24]
  personaldocs access-policy unblock-ip 203.0.113.7
  personaldocs access-policy clear-automatic  # remove automatic failed-login blocks

Every action is written to the audit log as a console action.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.core import audit
from apps.security import netutil, policy
from apps.security.models import CountryRule, GeoPolicy, IPRule


class Command(BaseCommand):
    help = "Show or recover the geographic/IP access policy from the server console."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["status", "off", "rollback", "trust-ip", "unblock-ip", "clear-automatic"])
        parser.add_argument("address", nargs="?")
        parser.add_argument("--hours", type=int, default=0, help="Expiry for trust-ip (0 = no expiry)")

    def _audit(self, action, **ctx):
        audit.record(f"security.console_{action}", actor_label="console", **ctx)

    def handle(self, *args, **opts):
        action = opts["action"]
        pol = GeoPolicy.get()
        if action == "status":
            self.stdout.write(f"Geographic policy: {'ENABLED' if pol.enabled else 'disabled'} · mode={pol.mode} · unknown locations={pol.unknown_action}")
            self.stdout.write(f"Allowed countries: {', '.join(CountryRule.objects.filter(kind='allow').values_list('country', flat=True)) or '-'}")
            self.stdout.write(f"Blocked countries: {', '.join(CountryRule.objects.filter(kind='block').values_list('country', flat=True)) or '-'}")
            for r in IPRule.objects.all():
                state = "active" if r.live() else "inactive"
                self.stdout.write(f"  {r.kind:8} {r.cidr:20} {state:8} {r.description}")
            return
        if action == "off":
            pol.previous = {"enabled": pol.enabled, "mode": pol.mode, "unknown_action": pol.unknown_action,
                            "allowed": list(CountryRule.objects.filter(kind="allow").values_list("country", flat=True)),
                            "blocked": list(CountryRule.objects.filter(kind="block").values_list("country", flat=True))}
            pol.enabled = False
            pol.version += 1
            pol.save()
            policy.invalidate()
            self._audit("policy_off")
            self.stdout.write(self.style.SUCCESS("Geographic access control disabled (rules kept). Re-enable it in Settings → Security & access."))
            return
        if action == "rollback":
            prev = pol.previous or {}
            if not prev:
                raise CommandError("No earlier policy recorded. Use 'off' instead.")
            pol.enabled, pol.mode, pol.unknown_action = prev.get("enabled", False), prev.get("mode", "off"), prev.get("unknown_action", "allow")
            pol.previous = {}
            pol.version += 1
            pol.save()
            CountryRule.objects.all().delete()
            for c in prev.get("allowed", []):
                CountryRule.objects.create(country=c, kind="allow")
            for c in prev.get("blocked", []):
                CountryRule.objects.create(country=c, kind="block")
            policy.invalidate()
            self._audit("policy_rollback")
            self.stdout.write(self.style.SUCCESS("Previous access policy restored."))
            return
        if action == "clear-automatic":
            n = IPRule.objects.filter(automatic=True).delete()[0]
            policy.invalidate()
            self._audit("clear_automatic", removed=n)
            self.stdout.write(self.style.SUCCESS(f"Removed {n} automatic block(s)."))
            return
        if not opts["address"]:
            raise CommandError("Give an IP address or CIDR range.")
        try:
            net = netutil.parse_network(opts["address"])
        except ValueError as exc:
            raise CommandError(str(exc))
        if action == "trust-ip":
            expires = timezone.now() + timedelta(hours=opts["hours"]) if opts["hours"] else None
            IPRule.objects.create(cidr=str(net), kind=IPRule.TRUSTED, description="Added from the server console", expires_at=expires)
            policy.invalidate()
            self._audit("trust_ip", cidr=str(net))
            self.stdout.write(self.style.SUCCESS(f"{net} is trusted" + (f" until {timezone.localtime(expires):%Y-%m-%d %H:%M}." if expires else ".")))
            return
        n = IPRule.objects.filter(kind=IPRule.BLOCKED, cidr=str(net)).update(enabled=False)
        policy.invalidate()
        self._audit("unblock_ip", cidr=str(net), rules=n)
        self.stdout.write(self.style.SUCCESS(f"Disabled {n} block rule(s) for {net}."))
