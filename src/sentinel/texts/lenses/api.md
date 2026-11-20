# Lens: an interface other code calls (an API, a CLI, a function others use, a file format)

Sit in the caller's seat.

1. Who calls this today? Find the callers. What do they send, and what do they do with the answer?
2. What changes for each of them? What breaks if they are not changed at the same moment?
3. What does a caller get on bad input, on a missing thing, on a failure half way? Can they tell the cases apart and act on them?
4. Is a call safe to repeat? What happens when two arrive at once?
5. What is promised by the name and the shape that the code does not do, and the other way round?
6. Which permission does a caller need, and what stops one who lacks it?
7. How will a later version change this without breaking those who call it now?

Write the expected outcomes as calls with their answers, one for the ordinary case and one for each kind of failure.
