# Fragile patterns in how the work is done

Each line is a way the work goes wrong without anyone noticing at the time.

1. Deciding from cut output: a result read through `tail`, `head`, a size limit or a filtered grep, and treated as the whole.
2. Saying "not there" or "not possible" without looking: no search, no listing, no attempt behind the claim.
3. Acting before reading: an edit or a command before the code, the docs and the earlier decisions were read.
4. One observation taken as proof on something that varies from run to run.
5. Running everything again where the failing part alone would answer, or waiting blocked on a long run.
6. A fixed sleep where a condition should be waited for.
7. A summary that leaves out the step that failed or was skipped.
8. Committing in a checkout another session also works in without looking at what is staged.
9. Changing something shared (permissions, a tag, a port, a name, a config file) without checking who else uses it.
10. A setup or deploy script that makes new secrets, ids or names each time it runs, so a second run breaks the first.
11. Two environments that share a name, a tag, a port or a network, so one answers for the other.
12. A destructive command run before the target was looked at or a way back existed.
13. A fix for the symptom that was reported, with the general fault left in place.
14. A check that passes because of where it ran: it reads local state, a cache, or yesterday's build.
15. Testing only what was just changed and calling the whole thing working.
16. Trusting a remembered result after a compaction or a restart without checking it again.
