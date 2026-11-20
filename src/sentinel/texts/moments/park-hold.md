Claude Code is about to compact your context{tokens}, and Sentinel is holding the compaction back so that you can write your notes first. After the compaction you keep a summary and your files; the rest of your context goes.

Do this now, before you answer the person or take the next step of your work. Bring {notes} up to date:
1. Where you are, and exactly what comes next.
2. What is running in the background or with subagents, and what of theirs you have not read yet.
3. Every open doubt, every value still to confirm, every question the person has not answered.
4. What you learned about this code, these tools and this person that no file holds yet.
5. Any correction the person gave you that is not recorded yet: record it now with `sentinel learn`. <!-- if:learn -->

Then run `sentinel park done`. The compaction goes ahead by itself after that. When it is over you are given your history, your notes and your tasks to read back, and you carry on from there.
Until you have run it, read no large file and start nothing new: the hold ends by itself when the context reaches {limit} tokens, with the notes or without them.
