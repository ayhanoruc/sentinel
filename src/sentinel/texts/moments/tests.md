You are about to write tests. Before you do:
1. A test earns its place by the failure it would catch. For each test, name the change to the code that would make it fail. If you cannot, do not write it.
2. Prefer one end-to-end test that goes through the real path and prints what it did at each step, so that when it fails later the output alone shows where. Do not replace the real thing with a mock and then assert on the mock.
3. Do not write tests that restate the code, and do not write a test only because code was added. A check you run once by hand and record in the contract's Proof is better than a test nobody needs to keep.
4. Keep a test when the behaviour can break silently later. See it fail once before you trust it.
5. A test must not depend on today's date, on the order of other tests, or on what another run left behind.
