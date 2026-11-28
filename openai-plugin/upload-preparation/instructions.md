
### Preparing exact text from a local file

For an authorized file upload, use the helper beside this skill. Run `python3 -I -B prepare_upload.py < "$source"` from the skill directory or give the path to that script. If the request refers to previously reviewed bytes, add `--reviewed-sha256 "$recorded_digest"` using the earlier digest. A changed source exits 3 with no upload fields. Reinspect that file while independent work proceeds.

Use the two fields from its JSON output directly as structured values for `rumbo_ingest_artifact`. Preserve JSON escaping, including CRLF and trailing newlines. Supply the task, filename, contract revision and previously observed artifact revision yourself. The helper reads stdin and emits JSON locally. Send it only when the existing authorization covers that exact content and destination. If the call has an uncertain result, read the current revision and digest before retrying.
