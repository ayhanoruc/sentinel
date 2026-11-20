1. Scope: does this change do what the task's contract says and nothing outside it? Name anything extra.
2. World model: for each expected outcome in the contract, what did you observe? Write "not checked" where you did not look.
3. Unhandled cases: which inputs, states or users does this not handle, and what happens to them?
4. Fragile patterns: read `sentinel catalogue`. Which entries apply to this change or to how you worked, and what did you do about each?
5. Usual practice: where does this differ from how the field usually does it, and why is that right here?
6. Proof: what exactly shows that this works (the command and what you saw)? For each new test: which breakage would make it fail, and did you see it fail?
