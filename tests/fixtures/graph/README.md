# Offline Graph contracts

Every JSON file here is **synthetic_contract_fixture**, authored from SPEC §11 and Meta's
[official Instagram API workspace](https://www.postman.com/meta/instagram/overview).
These are not captured responses, real tokens, real media, or evidence of successful live posting.
Numeric resource IDs and example.org media URLs are placeholders. The declared render recipe
in test factories is synthetic metadata; no Wan render was run.

Publisher scenarios cover photo, image carousel and reel creation, FINISHED, ERROR, EXPIRED,
IN_PROGRESS, PUBLISHED, quota exhaustion, known rate rejection, malformed resource IDs,
unknown status and ambiguous timeouts/5xx. Exchanges are ordered and match full parameters.
Insights scenarios cover modern `views`, lifetime value/total-value shapes, missing/empty data,
zero reach, overlapping interaction counts and reel average watch time in milliseconds.

The strict fake fails on unknown, out-of-order or unused exchanges. `make test` disables sockets.
Native HTTP tests use httpx.MockTransport, synthetic sentinels and no real API keys.
# HUMAN: validate these contracts against your app's supported API version and permissions
before making a live post; never add raw response text containing credentials to fixtures.
