"""Optional InfluxDB 2 output: line protocol over the HTTP write API, stdlib only.

Two measurements, written with the sample's own timestamp (seconds), so replaying the same
data overwrites the same points:

  defenestrator_usage  tags host, provider (claude|codex); fields u5, u7 (percent), reset5, reset7
                       (epoch s), capped (bool). A weekly-only plan has no u5/reset5.
  defenestrator_event  tags provider, kind; fields reason (string), reset (epoch s)
  defenestrator_use    tags model, project; fields cost (API-equivalent $), pct (estimated % of the
                       5-hour budget), one point per 10 minutes, from the session logs on this machine
"""
from __future__ import annotations

import os
import urllib.request


def _esc_tag(v):
    return str(v).replace("\\", "\\\\").replace(",", "\\,").replace("=", "\\=").replace(" ", "\\ ")


def _esc_str(v):
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def usage_line(sample, host, provider="claude"):
    fields = []
    for k in ("u5", "u7", "reset5", "reset7"):
        if sample.get(k) is not None:
            fields.append(f"{k}={float(sample[k])!r}")
    fields.append(f"capped={'true' if sample.get('capped') else 'false'}")
    return f"defenestrator_usage,host={_esc_tag(host)},provider={_esc_tag(provider)} {','.join(fields)} {int(sample['t'])}"


def event_line(event, host):
    fields = [f"reason={_esc_str(event.get('reason', ''))}"]
    if event.get("reset") is not None:
        fields.append(f"reset={float(event['reset'])!r}")
    return (f"defenestrator_event,host={_esc_tag(host)},provider={_esc_tag(event['provider'])},"
            f"kind={_esc_tag(event['kind'])} {','.join(fields)} {int(event['t'])}")


def use_line(t, model, project, cost, pct_per_dollar, host):
    return (f"defenestrator_use,host={_esc_tag(host)},model={_esc_tag(model)},project={_esc_tag(project)} "
            f"cost={float(cost)!r},pct={float(cost) * pct_per_dollar!r} {int(t)}")


class Influx:
    """Best-effort writer: a failed write is reported to the caller, never raised."""

    def __init__(self, url, token, org, bucket, host):
        self.url, self.token, self.org, self.bucket, self.host = url.rstrip("/"), token, org, bucket, host

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        if not env.get("INFLUX_URL") or not env.get("INFLUX_TOKEN"):
            return None
        import socket
        return cls(env["INFLUX_URL"], env["INFLUX_TOKEN"], env.get("INFLUX_ORG", "defenestrator"),
                   env.get("INFLUX_BUCKET", "defenestrator"), env.get("INFLUX_HOST_TAG") or socket.gethostname())

    def write(self, lines, batch=5000):
        """POST line protocol; returns an error string or None."""
        lines = list(lines)
        for i in range(0, len(lines), batch):
            body = ("\n".join(lines[i:i + batch]) + "\n").encode()
            req = urllib.request.Request(
                f"{self.url}/api/v2/write?org={self.org}&bucket={self.bucket}&precision=s",
                data=body, method="POST",
                headers={"Authorization": f"Token {self.token}", "Content-Type": "text/plain; charset=utf-8"})
            try:
                urllib.request.urlopen(req, timeout=15).close()
            except Exception as e:  # network/HTTP errors: class only, never the token
                return f"influx write failed ({type(e).__name__}: {getattr(e, 'code', '')})"
        return None

    def write_usage(self, samples, provider="claude"):
        return self.write(usage_line(s, self.host, provider) for s in samples)

    def write_use(self, use, pct_per_dollar):
        """use: {(hour, model, project): cost}."""
        return self.write(use_line(h, m, p, c, pct_per_dollar, self.host) for (h, m, p), c in use.items())

    def write_events(self, events):
        return self.write(event_line(e, self.host) for e in events)
