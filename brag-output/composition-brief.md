# Hyperframes Composition Brief: Kova

## Objective
Create a short, polished, highly engaging launch brag video for Kova.

## Output
- Composition directory: `brag-output/composition/`
- Rendered video: `brag-output/brag.mp4`
- Format: landscape — 1920x1080
- Duration: 18 seconds (540 frames at 30fps)

## Source Material
- Project root: `/home/codegallantx/moi/kova`
- Primary files read: `README.md`, `frontend/app/globals.css`, `frontend/components/marketing/landing-redesign.tsx`
- Product name: Kova
- Tagline / strongest claim: "Let an agent use your software. Give Kova a website and a goal. It explores the product, figures out what needs to happen, and executes the journey like a real user."
- Key UI or visual moment to recreate:
  - The URL input pill (`https://yourproduct.com` -> `Explore →`)
  - The browser mockup with autonomous cursor navigation and modal dismissal
  - The floating glass report card with green checks and screenshot evidence grid
- Copy that must appear verbatim:
  - "Let an agent use your software."
  - "AI Proposes. Code Disposes."
  - "Autonomous software agent"
  - "Explore →"

## Creative Direction
- Tone preset: polished
- Creative direction: Sharp, editorial launch film with high-craft typography and startup swagger
- Interpretation: Fast-paced yet legible cuts, warm editorial palette, confident claims, zero generic SaaS buzzwords.
- Angle: Modern teams waste days maintaining brittle testing scripts or manually clicking through apps before every deploy. Kova acts as an autonomous user that explores, handles roadblocks like auth and modals, and verifies outcomes with cryptographic proof.
- Hook: The first 3.5 seconds feature the bold editorial title and typing URL pill.
- Outro / punchline: "AI Proposes. Code Disposes." followed by the Kova brand mark and URL.
- Avoid:
  - Generic SaaS language
  - Abstract filler visuals
  - Unrelated visual redesign

## Visual Identity
- Background: #FBF7F0 (warm cream sand)
- Text: #2A170D (deep espresso ink)
- Accent: #D58A56 (warm terracotta clay) & #8A3513 (deep rust)
- Secondary / Card: #FFFFFF with soft amber/rust shadows
- Display font: Bricolage Grotesque (via Google Fonts)
- Body font: DM Sans (via Google Fonts)
- Visual references from the project:
  - Radial gradient backdrops with floating ambient orbs (`#E9A878`, `#C9733F`)
  - Floating glass cards with subtle borders (`rgba(42, 23, 13, 0.1)`)
  - Dot-grid container backgrounds

## Storyboard
Use the storyboard in `brag-output/brag-plan.md` as the creative contract.

Scene summary:
1. Hook & Target Entry — 3.5s (0.0s–3.5s) — Headline "Let an agent use your software.", interactive URL pill typing `https://yourproduct.com`, cursor clicks `Explore →`.
2. Autonomous Exploration — 5.0s (3.5s–8.5s) — Browser mockup appears, autonomous cursor navigates, install-app modal popup appears and gets dismissed via "Got it", exploration continues seamlessly.
3. Cryptographic Evidence — 4.5s (8.5s–13.0s) — Verification cards: "Report" with sequential green checks, 4-tile screenshot evidence grid, "No brittle scripts. Cryptographic evidence."
4. Punchline & Outro — 5.0s (13.0s–18.0s) — "AI Proposes. Code Disposes." Logo mark "Kova.", badge "Autonomous Product-Flow Testing", and "kova.dev".

## Audio
- Audio role: warm bed with crisp UI accents
- Audio arc: Bouncy, upbeat rhythm starts immediately; mechanical clicks and UI whooshes punctuate interactions; builds to a confident verification crescendo and settles into a warm branded outro.
- Music: `happy-beats-business-moves-vol-10-by-ende-dot-app.mp3`
- Music treatment: Plays from 0.0s to 18.0s at -12dB gain, fading out smoothly over the final 1.5s.
- Music cue guidance: Preset cues available in `assets/music/cues/happy-beats-business-moves-vol-10-by-ende-dot-app.music-cues.md`.
- Audio-coupled moments:
  - 1.0s–2.0s: Rapid typing sounds for URL entry.
  - 2.4s: Mouse click on `Explore →`.
  - 5.0s: Modal dismiss click.
  - 9.2s–10.5s: Success check chime.
  - 13.5s: Subtle bass impact on final statement.
- Audio files: Copied into `brag-output/composition/assets/`

## Hyperframes Instructions
- Use local assets for audio.
- Run `npx hyperframes check` before render.
- Ensure all text passes WCAG contrast and layout bounds.
