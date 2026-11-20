Task {id} is open ({size}). Its contract: {path}

Before you edit anything for it:
1. Read what the work touches first. Do not write the contract from the request alone.
2. Fill every section of the contract file. Short lines that can be checked.
3. Present it to the person in the conversation, in their language and sized to the task: what you understood, the options and the one you recommend, what you assume, what you need answered. Do not assume they know the area: say what the usual practice is, and where you would do it differently from what they asked.
{field_note}
4. Stop and wait for their answer. The request itself is not the answer: they have not seen your contract yet.
5. When they have answered and agree, record it with their own words from that answer: `sentinel task approve {id} --basis "<their words>"`.
   Only if they told you not to wait for them (they are away, or said to go on without asking): `sentinel task approve {id} --standing "<the words they said that with>"`, and put the contract's understanding, assumptions and questions in your final message. <!-- if:tasks.standing -->

Steps inside this task need no contract of their own: `sentinel task open "<step>" --parent {id}`.
When the work is done and shown to work: `sentinel task done {id}`.
