# org-quartz

Publish org-roam notes as a static site using Quartz. Public version hosted at [andanao.github.io/org-quartz/](https://andanao.github.io/org-quartz/)

! This has been almost entirely done through claude-code

## Setup

Requires: Node.js 20+, Python 3.12+, Emacs

```bash
npm install
```

## Usage

### Local development

```bash
./scripts/build.sh personal   # Build with personal notes only
./scripts/build.sh combined   # Build with personal + k2 notes
npx quartz build --serve      # Serve at http://localhost:8080
```

### Deploy to NUC (combined)

```bash
./scripts/deploy-nuc.sh
```

### GitHub Pages (personal only)

Push to `main` triggers automatic deployment via GitHub Actions.

Requires `ORG_REPO_TOKEN` secret with read access to your org repo.

### Share a single note

Export one note as a standalone file to send to someone outside the network —
meeting notes to a customer, a plan to a client, a book review to a friend:

```bash
./scripts/share.sh "Acme kickoff"        # -> share/acme-kickoff.html
./scripts/share.sh acme-kickoff --pdf    # -> ... and share/acme-kickoff.pdf
```

Reads from `public/`, so build first if the note has changed. Takes a slug or a
title; an ambiguous title lists the candidates instead of guessing.

The output keeps the note, its title and its date, and drops everything that
would expose the rest of the vault — explorer, graph, backlinks, search index,
tags. Internal wiki-links become plain text, so nothing names an unpublished
note or dead-ends. CSS, webfonts and images are inlined, so it's a single file
that renders identically with no network and no server.

There's also an in-page version of the same thing: builds run through
`build.sh` or `deploy-nuc.sh` include share controls at the foot of each note,
hidden until you visit any page once with `?share=1` (`?share=0` to hide them
again). On a phone these hand off to the native share sheet, so the note goes
straight into Mail or Messages. The GitHub Pages workflow calls `npx quartz
build` directly and so ships neither the markup nor the script.

## How it works

1. `filter.py` collects org files, excluding `:private:` tagged files
2. Files tagged `:ppl:` keep their node but have body content stripped
3. `export.el` batch-converts org to markdown with YAML frontmatter
4. ID links (`[[id:uuid]]`) and roam links (`[[roam:Name]]`) are resolved to wiki-links
5. Attachments are copied and linked
6. Quartz builds the static site with backlinks, graph, and search

## Configuration

- `filter.py` — Source dirs, excluded tags, body-stripping tags
- `quartz.config.ts` — Site title, theme, plugins
- `quartz.layout.ts` — Page layout
- `quartz/share/strip.ts` — What a shared note keeps and drops (used by both
  `scripts/share.sh` and the in-page button)
