This command is held: it cannot be undone ({patterns}).

Before it runs:
1. Look at the target: list it, read it, or inspect it. Say what you saw.
2. Name the way back: the backup, the commit, the copy. If there is none, say so.
3. If someone else may depend on the target (another session, a running service, the person), say that too.
4. Then record it and run the same command again:
   sentinel gate ok {token} --target "<what you looked at and saw>" --rollback "<how to undo it, or why there is no way back>"

The acknowledgement is for exactly this destructive command in this folder, once. What you chain around it may change; the command itself, the folder and any `cd` before it may not.
