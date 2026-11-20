Review {id}{task}: {status}

Files reviewed:
{files}
{facts}

Flagged lines:
{findings}

{questions}

What to do:
1. For each flagged line that is open: fix it in the code, or keep it and say why this value or this fallback is right:
   sentinel review set F<n> fixed
   sentinel review set F<n> kept "<the reason>"
2. Answer each open question from what you actually did and saw: `sentinel review answer <n> "<answer>"`.
3. Tell the person in the conversation what you kept and why (these are the assumptions and numbers they should know about), and any risk you see.
4. Commit again. The commit passes when no flagged line and no question is open.
