# exulanica_client

A small client for a person's world through the Exulanica HTTP API, written against the Python
standard library only. It reads the person's saved world, asks the server which edits, behaviours
and assets it supports, places a reviewed object, gives it bounded motion, and confirms the result
on a fresh read.

```bash
EXULANICA_TOKEN=<token> python3 -m exulanica_client walkthrough --base-url https://<api> \
  --origin-role fictional --place 0,0,0 --asset-key cc0.marker-cube
```

Run it from this directory, or put this directory on `PYTHONPATH` to import `exulanica_client` in
another program. The token needs `world.read` and `world.write` and nothing else. The guide is
[docs/capabilities/developer-client.md](../../docs/capabilities/developer-client.md).
