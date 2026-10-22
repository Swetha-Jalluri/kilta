# Start here (Mac, about 30 minutes)

## 1. Install the tools
If you don't have Homebrew, install it from brew.sh first. Then in Terminal:
```bash
brew install uv node gh
brew install --cask ollama        # or download the app from ollama.com
gh auth login                      # log in to GitHub
```
Google Chrome is needed for voice (Web Speech API).

## 2. Get the free AI keys and models
- Gemini: go to Google AI Studio, sign in, create an API key. Check the exact current Flash model IDs there.
- Ollama backup (needs roughly 16 GB RAM for an 8B model; use a smaller model on 8 GB Macs):
```bash
ollama pull qwen3:8b               # or a smaller tool-calling model, see ollama.com/library
```

## 3. Create the repo and add this kit
```bash
gh repo create kilta --public --clone --description "Kilta: a warm, voice-first repair friend for Alexa+"
cd kilta
# unzip the kit in Downloads, then copy everything, including the hidden .claude folder:
cp -R ~/Downloads/kilta/. .
cp .env.example .env               # then paste your GEMINI_API_KEY into .env
# edit LICENSE: replace [Your Name]
git add -A && git commit -m "Project kit: plans, rules, Claude Code setup"
git push -u origin main
```
On GitHub, set the repo's About section so the MIT license shows.

## 4. Set up Claude Code (one time)
```bash
claude mcp add playwright -- npx @playwright/mcp@latest   # lets Claude test the UI in a real browser
claude                                                    # start in the repo folder
```
Inside Claude Code, run `/context` and confirm CLAUDE.md loaded.

## 5. Also today
- Request Alexa+ Private Preview access (developer.amazon.com, Alexa+ add-ons / MCP Toolkit). Don't wait on it.
- Note anything painful with `/friction`.

## 6. Build, one phase per session
```
/clear
/phase 1
```
Read the plan it proposes. Approve (or press Ctrl+G to edit). Let it build. It must show test output.
Then the next phase in a fresh session: `/clear` then `/phase 2`, and so on (see docs/phases.md).

## Controls you'll use
- Shift+Tab: cycle modes (plan mode)        - Esc: stop      - Esc Esc or /rewind: undo to a checkpoint
- /clear: fresh context between phases      - /compact: shrink a long session
- /rename phase-1-server: name the session  - claude --continue: resume last session
- @docs/file.md: point Claude at a file     - /btw: quick side question

## Rules of thumb
- Always ask for proof (tests, screenshots). After two failed fixes, /clear and re-prompt with what you learned.
- Commit after every working step. Feature freeze Thursday 10 PM. Friday = record + submit by 10 AM ET.
