#!/bin/bash
# Run AFTER `npx quartz build`.
#
# Quartz's slugifyFilePath strips the .html extension from static assets, so an
# HTML attachment lands in public/attachments/ without an extension and nginx
# serves it as application/octet-stream (forcing a download instead of opening
# it in the browser). Restore the .html extension so nginx serves text/html.
#
# Internal links to the file are extensionless (Quartz strips .html from hrefs
# too), but the site's nginx uses `try_files $uri $uri/ $uri.html`, so the
# extensionless URL resolves to the .html file. No href rewriting needed.
set -e
cd "$(dirname "$0")/.."
shopt -s nullglob

count=0
for f in content/attachments/*.html content/attachments/*.htm; do
  [ -e "$f" ] || continue
  base="$(basename "$f")"
  noext="public/attachments/${base%.*}"   # extensionless file Quartz emitted
  target="public/attachments/${base}"     # restore the .html name
  if [ -e "$noext" ] && [ ! -d "$noext" ]; then
    mv -f "$noext" "$target"
    count=$((count + 1))
  elif [ -d "public/attachments" ]; then
    cp -f "$f" "$target"
    count=$((count + 1))
  fi
done

echo "Restored .html extension on $count HTML attachment(s)"
