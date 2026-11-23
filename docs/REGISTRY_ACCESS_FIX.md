# PROSPERO and OSF Registries access repair

Date: 2026-11-23
Scope: systematic-review protocol discovery. No registry record creation or submission.

## Production diagnosis

Two completed Cardiology jobs had 0 qualified options partly because
PROSPERO returned ACCESS_FAILED and OSF returned PARTIAL for every verified
topic. Neither finding proves that a topic lacked novelty.

### PROSPERO

The previous GitHub Actions step called:

`npm install -g github:erichuang777777/PROSPERO-MCP#v0.2.2`

GitHub Actions reported a successful npm exit but no `prospero` executable
and no `dist/cli.js` file. The Python adapter therefore never reached the
public PROSPERO registry.

The repaired worker:
1. clones the pinned v0.2.2 source of the read-only PROSPERO-MCP project;
2. installs Node dependencies and builds TypeScript;
3. validates that `dist/cli.js` exists;
4. passes the absolute script path as `PROSPERO_CLI_JS` to the Python worker;
5. runs read-only search commands through Node, never a registered-study write.

The Python adapter validates `ok`, `total_hits`, and the `hits` list.
It supports bounded pagination and returns PARTIAL if more matches exist than
were retrieved. A malformed response never becomes a zero-hit result.

### OSF Registries

The previous implementation searched `/v2/registrations/?filter[title]=...`
with full PICO phrases. An empty title-only query was classified PARTIAL,
correctly, but produced many runs without useful registration matches.

The repaired source prioritizes the official OSF Trove public metadata search:

`https://share.osf.io/trove/index-card-search`

with `cardSearchText[title,description]`, resourceType `Registration`,
and `application/vnd.api+json`. It parses the JSON:API search-result
references, linked index-cards, registration title/description, and OSF IDs.
The free OSF v2 title filter remains a fallback if Trove is unavailable.
Pagination follows only trusted HTTPS links on `share.osf.io`, within a
bounded page budget. Previous results survive next-page errors.

For a search returning no matches or leaving more pages unseen, the status
remains PARTIAL rather than claiming a definitive negative registration search.

## Real integration verification

GitHub Actions workflow: `registry-connection-check`
Run: https://github.com/ahmedkam997/scimed-srma-scout-cloud/actions/runs/45125564124

Read-only real-world smoke query: `heart failure`, first page, three items.

- PROSPERO: HTTP/API search worked, 3 records, 18,468 matched the broad query.
- OSF Trove: public search worked, 3 registrations, 581 matched the broad query.
- Both were correctly classified PARTIAL because only one result page was
  evaluated, not because of API or installation failure.
- Python CI, registry adapter pagination tests, and JavaScript syntax
  checks passed on GitHub Actions.

## Remaining scientific coverage limits

Broad metadata queries routinely return hundreds or thousands of matches.
Exhaustive comparison across all matches is not possible under short API
windows and free inference quotas. The Scout therefore has to distinguish:

- **ACCESS_FAILED**: source not reachable, installation failed, or API error.
- **PARTIAL**: source accessible, but indexed result pages or search scope not
  exhaustively assessed.
- **SEARCHED_POSITIVE**: a completed bounded query retrieved registry records.
- **SEARCHED_NEGATIVE**: a source explicitly confirmed zero for the exact query.
  Only a confirmed successful complete search permits this status.

No negative inference follows from an unsuccessful API request, a short
metadata-only query, or retrieval of the first page of 18,468 hits.

To confirm a first-choice review topic, a human research reviewer must
resolve relevant registration matches and revisit both official search
interfaces when broad search coverage is incomplete. The app retains this as
a TYPE-A blocker, and still displays qualified vs provisional leads separately.

## Documentation and sources

- Official PROSPERO search: https://www.crd.york.ac.uk/PROSPERO/search
- Open-source PROSPERO-MCP v0.2.2:
  https://github.com/erichuang777777/PROSPERO-MCP
- Official OSF Trove search API:
  https://share.osf.io/trove/docs/openapi.html
- OSF support explanation of text-index and metadata scope:
  https://help.osf.io/article/588-getting-started-with-osf-search
- OSF API v2 registrations:
  https://developer.osf.io/
