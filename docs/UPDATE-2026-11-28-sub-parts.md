# November 28 Claude adapter 0.3.29: the adapter tested sub-part by sub-part

This is the second of three passes over the Claude adapter, each going down a level: its parts in [0.3.28](UPDATE-2026-11-28-parts.md), their sub-parts here, then single functions and branches. Each part was split into the sub-parts that read or decide one thing. Each sub-part was probed with a phrasebook of the ways users write that thing, and each was checked against the coverage report of the suite on 0.3.28. That report listed 114 statements and 64 branches no test ran.

## Distribution identities

- The Claude adapter is **0.3.29**.
- The Python engine **0.3.6**, the OpenAI portable and Codex local adapters **0.3.8** and the Sites candidate **0.1.3** are unchanged. The Codex local package bundles this source tree's `rumbo/scripts/record.py`, so a package built from here carries this code under its own unchanged version.

## The sub-parts and what testing them found

| Part | Sub-part | How it was tested | Found |
| --- | --- | --- | --- |
| Source readers | Numbers in digits and words, and scales | 113 phrasings | As the SPEC says. Forms it does not read stay unread: "a dozen", a decimal comma ("€2,50" reads as 250), "$3B" |
| | Money's exclusions | The 0.3.28 fast path against 0.3.27, on 1.27 million random texts | A no-break space changed readings (fixed before 0.3.28 merged) |
| | Zero factors | 27 phrasings | "sugar-free" read as a zero price; "$25 a seat" and "$25/seat" were no rate (fixed) |
| | Clock times | 30 phrasings | "9.30pm" was no time, though money already read it as one; "2-4pm" and "9-10:30" did not source their start (fixed) |
| | Durations | 46 phrasings | As the SPEC says |
| | Dates | 54 phrasings | "2026-03-20T10:00" read its time but not its date; "2026/03/20" and "June 3 to 5" were not read (fixed) |
| Record validation | JSON, record shape, check values | Each uncovered rule | As the SPEC says. The time reader raised on "²:00", which validation rejects first (guarded) |
| | Outcome ledger | Each of its 18 rules | Consistent with the SKILL |
| Outcomes and handoff | Artifact states, report status, `show` lines, `handoff` errors, project root | Each state and exit, on disposable projects | Consistent |
| Hook commands | Loop guard, told counts, terminal stdin, state directory | Each branch, through the commands | Consistent: another user's state directory keeps no state, and the gate then enforces nothing that needs it |

Line and branch coverage of `record.py` by its own tests is now 97%: 72 statements and 36 branches are left, nearly all of them `except OSError` handlers for a disk that fails.

## What changed

- **"sugar-free" is not free.** A zero price per unit needs `free`, `at no charge` or zero money next to its quantity. `free` after a hyphen now counts only when a price comes before it (`cost-free`, `fee-free`, `rent-free`, `toll-free` and the like). `Sugar-free snacks for 12 kids` no longer sources a price of 0.
- **A rate can be written "a seat" or "/seat".** A zero quantity is sourced by "no seats" only when the user gave a price per seat. That price could be written only as `$25 per seat`; now `$25 a seat` and `$25/seat` count too.
- **"9.30pm" is a time.** A dot before the minutes makes a time only with am or pm after it on the same line, as the money reader already read it: `9.30pm` sources 21:30, and `9.30` alone sources nothing.
- **A range's bare start is a time.** In `2-4pm`, `9 to 11am` or `9-10:30`, the first hour now sources its time. With am or pm on the end, the start is the hour up to 12 hours before the end: `2-4pm` sources 14:00, `11-1pm` 11:00 and `8-1am` 20:00. With none, it reads like any time without am or pm: `9-10:30` sources 09:00 and 21:00. An end with neither minutes nor am/pm makes no time, so `June 3-5` and `9 to 5` source none. Such a start is also no money, as `4pm` already was: `The workshop runs 2-4pm` no longer sources $2.
- **More dates are read.** `2026-03-20T10:00` sources March 20, as it already sourced 10:00. `2026/03/20` sources March 20. A range joined by `to`, `through`, `thru`, `until` or `till` sources both ends, as a dash already did, never the days between: `June 3 to 5` sources June 3 and June 5.
- **Times are read once per text.** The new forms add passes over the text, and the hooks read the same quotes for each check's start and end. The times a text states are now kept, as its numbers already were.
- **The time reader reads the digits validation reads.** Validation takes decimal digits of any script (`٠٩:٣٠`, kept since October). The reader checked for any digit instead, and `int()` cannot read `²`. It now checks for decimal digits too, so a malformed time returns no match instead of raising.

The reply reader uses the same readers, so a reply that says `2-4pm` or `9.30pm` states that time.

## Evidence

- `rumbo/tests/test_sub_parts.py` holds 24 tests, one or more per sub-part. On 0.3.28, 10 of them fail: 35 phrasings read wrongly and 3 malformed times raise. The ledger, handoff and hook tests pass on both versions, as tests of branches that had none should.
- Across the 207 saved records (1,053 checks), no validation, unsourced value, check result or problem line changes, nor any reading of their 142 distinct quotes. The replay of the saved Stop blocks (80 blocks in 57 runs) is identical. The new forms do not occur in the eval prompts. The fixes are for how people write elsewhere.
- Times are now read once per text, as numbers are, so a quote is not scanned again for each start and end time. On 1.2 MB quotes of times, numbers, number ranges and dates, reading one time, one date and the money takes 16% less to 14% more time than on 0.3.28, all under 4.1 s. On 219,314 random texts and 125 times, the time reader answers as it did before it was cached.
- Both suites pass, with their output saved.

## Verification and rollback

```sh
(cd rumbo && python3 -m unittest discover -s tests)
python3 -m unittest discover -s tests
```

To roll back, return to the 0.3.28 merge on main. There is no data migration.
