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
