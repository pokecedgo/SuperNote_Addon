# SuperNote(Ced++)

A study buddy that runs on your laptop next to your Supernote and leaves comments on your notes while you write in class.

Mirror your Supernote's screen to your Mac, press **Record**, and write as usual. Whenever you pause, **Ced++** reads the new handwriting and pins a short comment beside it, the way a collaborator comments in Google Docs.

> You write `∇f = ⟨∂f/∂x, ∂f/∂y⟩`
> **Ced++ · Gradient formula:** "Hey, this is the gradient! It points in the direction of steepest increase of f."
> *You could also note:* `Dᵤf = ∇f · u` · `|∇f|` is the max rate of increase

If a line has a likely slip, such as a wrong sign or a wrong derivative, the comment gets a **HEADS UP** tag.

The app is styled like the Supernote interface: black ink on warm paper, thin black outlines and soft rounded corners.

---

## Install (macOS, Terminal)

SuperNote(Ced++) needs **Python 3.10 or newer**. The Python that ships with macOS is 3.9, so the easiest route is [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/pokecedgo/SuperNote_Addon.git
cd SuperNote_Addon

brew install uv
uv venv --python 3.12
source .venv/bin/activate
uv pip install -r requirements.txt
```

`uv venv --python 3.12` downloads Python 3.12 if you don't have it. No Homebrew? Install uv with `curl -LsSf https://astral.sh/uv/install.sh | sh` instead.

If you already have Python 3.10+ (for example from `brew install python@3.12`), this works too: `python3.12 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`.

### Claude API key

Ced++ uses Claude (`claude-opus-5`) to read your handwriting. Get a key from the [Claude Console](https://platform.claude.com/), then:

```bash
export ANTHROPIC_API_KEY=paste-your-real-key-here
```

Replace `paste-your-real-key-here` with your actual key (it starts with `sk-ant-`). To avoid retyping it, add that line to `~/.zshrc`.

Each comment is one API call that sends two small images. You're billed per call.

---

## Run

Run **one** of these (after `source .venv/bin/activate`):

| Command | What it does |
|---|---|
| `python app.py` | Opens the app. Click **Connect** to pick your Supernote. |
| `python app.py --ip 192.168.1.42` | Connects straight to your Supernote (use the address it shows) |

**Try it without a Supernote:**

| Command | What it does |
|---|---|
| `python app.py --demo` | A simulated notebook writes a Calc III page, and Claude comments on it |
| `python app.py --demo --offline` | The simulated notebook with canned comments. No API key needed. |

### In class

1. **Supernote:** swipe down from the top and tap **Screen Mirroring**. Note the address it shows, for example `192.168.1.42`.
2. **App:** click **Connect** and type that address. **Scan Wi-Fi** can also find it for you. The address is remembered for next time.
3. Press **● Record** (or the **R** key). Everything already on the page is ignored. Only what you write from now on gets comments.
4. Write normally. About 2.5 seconds after you stop writing, a dashed box shows where Ced++ is reading, then a comment card appears beside that spot.
5. Click a card or its numbered box on the page to highlight the pair. **✓** resolves (hides) a comment.
6. Turn the page on your Supernote. The app notices the new page, and its comments start fresh.
**Ask about a specific area:** while recording, press **◌ Ask about area** (or **A**) and draw a loop around anything on the page. It can be old notes, a diagram, a formula, or a problem you're stuck on. Type a question if you like (or leave it blank), then press **Ask Ced++**. The answer appears as a comment pinned to the shape you drew, and your questions jump ahead of automatic comments. Press **Esc** to cancel.

7. Press **■ Stop**. The session is saved to `sessions/<date_time>/`:
   - `notes.md`: every comment, grouped by page, ready to paste into your notes
   - `comments.json`: the same comments with full detail
   - `page_N.png`: a snapshot of each page

### Lecture audio: side notes you'd otherwise miss

While you record, the app also records your Mac's microphone and transcribes the lecture as it goes. Transcription runs on your Mac with Whisper (large-v3-turbo on the Apple Silicon GPU), so the audio never leaves your computer.

- **Better comments:** each Ced++ comment also sees roughly the last 90 seconds of what the teacher said. It can link your notes to the explanation and point out things you didn't write down.
- **▶ on every comment** replays the lecture from just before you wrote that line.
- **When you press Stop,** the transcript is finished and one Claude call scans it for what was said *outside* the lecture topic. A **"Heads-up from today's lecture"** popup lists:
  - **Important, not part of the lecture:** exam dates and content, deadlines, homework, office hours, room changes, events. These are ranked by importance.
  - **Asides, tips & analogies:** "think of it like…", stories, study advice, and "this is important" moments.

  Each item shows the cue that gave it away ("by the way", "ojo", "before I forget", …) and has a ▶ button to hear it.
- **Accents:** the prompt tells Claude the teacher has an Argentine accent and mixes in Spanish (*bueno, o sea, ojo, ¿viste?*). It reads through transcription errors, but never invents dates or numbers.
- Each session folder also gets `lecture.m4a` (about 1 MB per minute), `transcript.txt`, `side_notes.json` and `lecture.md`.

Setup (one time; the Whisper model is a ~1.6 GB download on first use):

```bash
uv pip install -r requirements-audio.txt
```

macOS will ask for **microphone access** for your terminal app the first time: click Allow. Run with `--no-audio` to turn audio off. `--demo` plays a synthesized, Spanish-accented demo lecture so you can try it without a class.

Cost: transcription is free (it runs on your Mac). The side-notes scan is one text-only Claude call per lecture, roughly 10–20¢ for 75 minutes. Sending lecture context with comments adds a fraction of a cent per comment.

**Recording lectures:** check your school's policy, and ask your professor. Many schools require permission to record.

### Notebooks: store finished pages

When you finish a page, press **⤓ Store Page** (or **S**). You name the page and pick where it goes:

- **+ Notebook** creates a top-level notebook, such as *Calc III*. The first time you store a page, the app asks you for a notebook name.
- **+ Folder** creates a folder inside the selected notebook or folder. Folders can nest, for example *Calc III / Midterm 1 / Week 3*.
- The snapshot is saved with the Ced++ comments from that page.

Switch the top bar to **Notebooks** to browse what you've stored:

- Pick a notebook or folder on the left to see its pages as a numbered grid. **Drag** a page to reorder it.
- **Click a page** and its **Neat Copy** slides out from behind it: the same notes, transcribed and rewritten in tidy handwriting (your wording and your mistakes are kept, just made readable). Click it again, or click another page, to tuck it away.
- **Double-click** a page (or click **Open ›**) to open it. Each page has three buttons:
  - **Summarize Page**: the topic, a short summary, and the key points
  - **Important Takeaways for Exam**: what's likely to be tested and why, "watch out" mistakes (including ones on your page), and practice questions
  - **Delete**: removes the page, after asking you to confirm
- **‹ Move earlier / Move later ›** also reorder the open page.
- Summaries and takeaways are saved with the page, so reopening it doesn't cost another API call. "Summarize again" regenerates them.
- **Delete folder** removes a notebook or folder and everything in it, after asking you to confirm.

Neat copies are made automatically in the background when you store a page. For older pages, one is made the first time you click the page. Each neat copy is one Claude call, and it also saves a text transcript of the page, which is what makes search work.

### Search

Type in **⌕ Search** at the top (or press **⌘F**) to search every notebook at once. It matches page titles, the neat-copy text, Ced++ comments, your questions, summaries and exam takeaways. Matching ignores case and accents, and every word you type must appear. Results show where each match was found, with a highlighted snippet. Click a result to open that page; **Back** returns to your results. If some pages don't have a neat copy yet, the search results offer **Make neat copies** so their contents become searchable.

Everything is stored as plain files in `library/`, one folder per notebook or folder, with a `.png` and `.json` for each page. That makes it easy to back up or open in Finder. `library/` is git-ignored, so your notes stay on your Mac.

**Requirements for mirroring:** the Mac and the Supernote must be on the **same Wi-Fi**, with **no VPN or proxy**. Campus Wi-Fi often blocks devices from talking to each other. If Scan finds nothing, connect both devices to a **phone hotspot**.

---

## How it works

```
Supernote ──Wi-Fi──▶ http://<ip>:8080/screencast.mjpeg
                          │  MJPEG frames
                          ▼
                MirrorThread ── InkTracker (numpy)
                          │     • baseline = the page when Record was pressed
                          │     • new ink = pixels that turned dark since then
                          │     • erasing folds into the baseline
                          │     • pen idle 2.5 s → group new ink into regions → InkEvent
                          │     • most of the page changes and settles → new page
                          ▼
             TutorThread ── ClaudeTutor → Claude (close-up crop + whole page with a red box)
                          │     structured JSON: recognized, title, comment, extras, heads_up
                          ▼
         CommentStore → PageView anchors + CommentsPanel cards (Docs-style layout)
```

```
app.py                       entry point (flags, dependency check)
cedpp/
  config.py                  all tunables: pause length, thresholds, model, effort
  mirror/
    mjpeg.py                 multipart stream reader, address parsing
    sources.py               MirrorSource (Supernote), DemoNotebookSource (simulated writing)
    discovery.py             "Scan Wi-Fi": probes :8080 across your /24 subnet
  ink/tracker.py             new-handwriting detection, pause batching, page turns
  tutor/
    claude_tutor.py          Claude call: system prompt, JSON schema, refusal fallback
    offline_tutor.py         canned tips for --offline demos
    study.py                 Neat Copy transcription, "Summarize Page", "Important Takeaways for Exam"
    side_notes.py            finds announcements & asides in the lecture transcript
  audio/                     mic recording, live Whisper transcription, demo lecture
  comments.py                Comment model, per-page numbering, session export
  library.py                 Notebooks: nested folders, stored pages, ordering, search
  ui/                        PySide6: theme, main window, page view, comment cards
tests/                       pytest (tracker, stream parsing, tutor parsing, store)
```

### Tuning

Everything is in [`cedpp/config.py`](cedpp/config.py):

| Setting | Default | What it does |
|---|---|---|
| `InkConfig.pause_s` | 2.5 s | How long the pen must rest before Ced++ comments |
| `InkConfig.max_batch_s` | 12 s | Comment anyway during non-stop writing (at the next short gap) |
| `InkConfig.ignore_top/bottom` | 0 | Ignore a strip of the mirror, e.g. if your toolbar sits there |
| `TutorConfig.model` | `claude-opus-5` | Claude model used for comments |
| `TutorConfig.effort` | `low` | Raise to `medium` for deeper comments (slower, costs more) |

Requests use Claude's server-side refusal fallback (`fallbacks: "default"`), so a rare safety decline is retried on another model instead of failing the comment.

### Tests

```bash
pytest
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "Can't reach the Supernote" | Screen Mirroring must be on. The address can change after reconnecting to Wi-Fi, so check the popup again. Use the same Wi-Fi and turn off any VPN. |
| Scan finds nothing | The network probably isolates devices (common on campus). Use a phone hotspot for both devices. |
| "Ced++ can't sign in to Claude" | `export ANTHROPIC_API_KEY=...` in the same Terminal window, then restart the app |
| Comments on toolbar or menu changes | Set `ignore_top` or `ignore_bottom` in `config.py` to skip that strip. Ced++ also skips anything that isn't handwriting. |
| Too many or too few comments | Adjust `pause_s` and `max_batch_s` |
| Python 3.9 error | Use the uv install steps above |
