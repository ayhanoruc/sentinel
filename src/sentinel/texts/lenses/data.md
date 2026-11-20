# Lens: stored data, a schema, a migration, an import

Data outlives the code that wrote it.

1. What is already stored, and in what shapes? Look at real rows, including the old and the odd ones, not at the schema alone.
2. What does this change do to each of those shapes? Count before and after: rows, distinct keys, nulls.
3. Can it run twice? Can it stop half way and be run again? What state is the data in if it stops?
4. What is the way back: a backup, a reverse step? Was it tried?
5. Who else reads or writes this data (another service, a report, a person's export), and does it still work for them?
6. Which keys can collide, which ids are renumbered, which references point at something that moves?
7. What is lost: a column dropped, a value cut, a type narrowed, an encoding changed?

Write the expected outcomes as counts and as rows you can look up afterwards.
