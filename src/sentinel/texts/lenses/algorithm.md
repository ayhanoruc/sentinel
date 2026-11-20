# Lens: an algorithm, a calculation, a rule

Work it by hand before you trust the code.

1. Take three real inputs: an ordinary one, the smallest that makes sense, and an awkward one. Write the answer you expect for each before running anything.
2. What are the units and the ranges of every input and every output? What is out of range, and what happens then?
3. Which values can be missing or unknown? An unknown is never zero: what does the result say when one is?
4. Where does it round, sort, pick a first, or break a tie? Is that stable from run to run?
5. How does it grow: with ten items, ten thousand, a million? Where is the first limit it hits?
6. What must always be true of the result (it sums to the total, it never goes negative, the same input gives the same output)? Can that be checked in the code?
7. Who reads the number, and what will they do with it? Would they be misled by its precision?

Write the expected outcomes as inputs with the outputs you expect, and the properties that must hold.
