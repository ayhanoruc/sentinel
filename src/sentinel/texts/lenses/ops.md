# Lens: something that runs (a deployment, a job, a service, a script on a machine)

Think of the machine at three in the morning with nobody watching.

1. What is running there now, and who depends on it? What else shares its names, ports, volumes, credentials?
2. What exactly changes when this runs, in which order? What is the state if it stops between two steps?
3. What is the way back, and how long does it take? Is there a restore point from before?
4. How will you know it worked: which check, from where, reading what? How will you know tomorrow that it still works?
5. What does it need that may not be there: memory, disk, a network route, a secret, a permission, a newer version?
6. What happens on the second run, after a restart, on another machine?
7. What does it cost while it runs, and what stops it?

Write the expected outcomes as checks you will run and the answers you expect.
