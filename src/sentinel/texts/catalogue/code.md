# Fragile patterns in the code

Each line is code that works today and breaks, or lies, later.

1. A silent default: a missing value replaced by a fallback, so wrong input looks like valid input.
2. An unknown turned into zero or an empty value and then counted.
3. An error caught and dropped, or caught too widely, so the caller cannot tell it failed.
4. A magic number: a limit, a timeout, a size, a ratio in the middle of the code with no name and no reason.
5. Matching on text meant for people: an error message, a log line, a keyword list, a program's printed output.
6. Guessing meaning from words in code: a regex or keyword list deciding what a person or a document meant.
7. A fixed truncation: the first N items or characters taken without saying that something was cut.
8. Dependence on today: the date, the time zone, the locale, the machine's encoding, the current folder.
9. Dependence on order: of dictionary keys, of files in a folder, of tests, of parallel work finishing.
10. "The first one that matches" where several can match.
11. State shared without a rule: a file two processes write, a cache with no way to be invalidated, a global changed in passing.
12. A step that cannot be run twice: it appends again, creates again, regenerates a key.
13. A hard-coded path, address, port or account that belongs to one machine or one environment.
14. A retry or a loop with no bound, or a wait with no timeout.
15. A check by label where the exact thing should be checked: a tag for a digest, a name for an id, a length for content.
16. Two sources of the same fact that can drift apart: a copy of a list, a constant repeated in two files.
17. A boundary nobody validates: input from a file, a network or a person used as if it were already checked.
18. A test that cannot fail, or that asserts what a mock was told to return.
