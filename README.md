# timbre-profiles

A mirror of the [OPRA](https://github.com/opra-project/OPRA) headphone EQ dataset for Timbre. If upstream disappears or breaks, Timbre can keep working from this copy.

## Layout

- `opra/`: upstream files at the same paths (`database/vendors/...`, `dist/database_v1.jsonl`, licenses).
- `manifest.json`: upstream revision, commit date, sync time, file and product counts, and the SHA256 of the dist file.

## Sync

`.github/workflows/sync.yml` runs every day at 03:17 UTC and can also be started by hand.

| Result | What happens |
|---|---|
| New upstream commit | Validates every `info.json` and the dist JSONL, mirrors the files, commits |
| No change | Nothing is written |
| Upstream unreachable or invalid | Mirror is left as is; opens a `sync-alert` issue |
| More than max(25, 2%) of files removed | Mirror is left as is; opens a `sync-alert` issue. Rerun with `allow_deletions` after review |
| No upstream commits for 180 days | Warning in the run summary |

Small deletions are applied, and git history keeps the old files. Alert issues close on the next successful run.

Run it locally: `python3 scripts/sync_opra.py` (needs Python 3.9+ and git).

## License

The data under `opra/` is © the OPRA contributors, licensed under CC BY-SA 4.0. Data derived from AutoEQ is under MIT. See `opra/LICENSE.md` and `opra/THIRD_PARTY_LICENSES.md`. This mirror is redistributed under the same terms.
