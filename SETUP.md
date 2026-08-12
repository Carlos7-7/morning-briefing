# Setting up your morning briefing

## 1. Create the repo
Create a new GitHub repo (e.g. `morning-briefing`), public, same account you use
for your gig-tracker apps. Upload all these files into it, keeping the folder
structure exactly as-is (the `.github/workflows/` path matters).

## 2. Add your API key as a secret
In the repo: Settings -> Secrets and variables -> Actions -> New repository secret.
- Name: `ANTHROPIC_API_KEY`
- Value: the key you generated in the Anthropic console

This keeps the key out of your code entirely.

## 3. Enable GitHub Pages
Settings -> Pages -> Source: "Deploy from a branch" -> Branch: `main`, folder: `/ (root)`.
This is what makes `episodes/*.mp3` and `podcast.xml` publicly reachable at
`https://<your-username>.github.io/morning-briefing/`.

## 4. Test it manually first
Don't wait for 5:30 AM. Go to the Actions tab -> "Daily Morning Briefing" ->
"Run workflow" to trigger it by hand. Watch the run - this is where you'll catch
any dead RSS feed URLs or typos before trusting it to run unattended.

A few of the feed URLs in `topics.json` (Motor1, Herald-Dispatch especially) I
couldn't verify from my end - if a run logs a "failed to fetch" warning for one,
just swap in a working replacement URL for that topic.

## 5. Subscribe in Pocket Casts
Once a test episode has published successfully, open Pocket Casts -> Discover ->
paste this URL into the search bar:

`https://<your-username>.github.io/morning-briefing/podcast.xml`

It'll show up as a private podcast you can subscribe to like any other.

## 6. Let it run
Once steps 1-5 check out, leave it alone - it'll run automatically every morning,
email you if a run fails, and keep only the last 14 days of episodes.

## Notes on what's approximate right now
- RSS feed URLs: picked from generally reliable sources, but I couldn't hit them
  from a live connection while building this - expect to swap 1-2 out after the
  first test run.
- Voice/pacing: espeak-ng defaults to a serviceable but robotic voice at 165
  words/min. Both are one-line changes in `generate_briefing.py` if you want to
  try alternatives (`espeak-ng --voices` lists what's available).
- Script length: the prompt targets 4000-4500 words: worth checking the first
  episode's actual runtime and nudging that target if it's off.
