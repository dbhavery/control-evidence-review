# Issues log

Defects found while working on something else. Logged, not fixed, unless the fix was in
scope for the task that found them.

## 2026-09-20 — The BLOB redaction pattern destroys file paths, and provenance with them

**Severity:** medium. It does not leak anything. It deletes the one field an evidence
review exists to preserve.

**Found while:** building a real evidence corpus from an operating business and running
`controls/catalog-small-software-service.json` against it. Every evidence file carried a
provenance header naming its source path. The header came back like this:

```
Source: [REDACTED:BLOB]-privacy-and-data.md Read at commit: c0a1589
```

The source path was `angrynirds/content/sops/your-privacy-and-data.md`.

**What is wrong.** `cer/redaction.py:31`:

```python
("BLOB", re.compile(r"\b[A-Za-z0-9+/]{24,}={0,2}\b")),
```

`/` is a base64 alphabet character, so the class matches path separators. Any run of 24 or
more characters made only of letters, digits and slashes is treated as a high-entropy blob.
A file path is exactly that whenever it goes 24 characters without a hyphen, dot or
underscore. Measured:

```
angrynirds/content/sops/your-privacy-and-data.md  ->  [REDACTED:BLOB]-privacy-and-data.md
lib/concierge/budget.ts                           ->  unchanged (a dot arrives at char 22)
Projects/control-evidence-review/controls/...     ->  unchanged (hyphens break the run)
```

So whether provenance survives depends on where the first hyphen or dot happens to fall in
the path. That is the worst property a redactor can have: it is neither on nor off, and the
report looks fine unless you happen to read a header for a deep path.

**Why this is not fixed here.** Narrowing a redaction pattern trades a false positive for
the risk of a false negative, and a false negative in this function means a real secret
reaches a published report. That is not a call to make as a side effect of a different task.

**Suggested fix, not applied.** Require the run to contain at least one digit or at least
one of `+=`, which every real base64 or hex blob of that length has and a lowercase path
segment does not. Then add both cases to the redaction tests as a control: a genuine
base64 blob must still redact, and `angrynirds/content/sops/your-privacy-and-data.md` must
survive intact. A fix without the second test is the same bug with a different boundary.
