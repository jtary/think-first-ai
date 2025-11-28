# What does an LLM think about when its waiting?

Ok, so we have our basic app now. Let's see what happens when we spin up the LLM and give it a simple question and just don't respond right away.

![AI having social anxiety](./images/initial.png)

We can see that AI is not very good at waiting. Even though it could just quietly contemplate how to respond, it keeps poking us trying to re-engage (even though it's only been a few seconds).

I've found in the past that telling an LLM not to do something rarely works very well; instead, it's better to give it an alternative action to take. Let's add an extra tool to allow the AI to zone out for a few minutes if it doesn't have anything to say.

![AI after adding wait tool](./images/wait.png)