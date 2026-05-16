;;; export.el --- Batch export org files to markdown -*- lexical-binding: t; -*-

;; Usage:
;;   emacs --batch -l export.el --eval '(org-to-md "/path/to/input.org" "/path/to/output.md")'

(require 'ox-md)
(require 'org)
(require 'org-attach)

;; Override source block export to use fenced code blocks with language
;; Include tangle destination if present
(defun my-md-src-block (src-block _contents info)
  "Transcode SRC-BLOCK to fenced code block with language identifier.
Shows tangle destination if present."
  (let* ((lang (org-element-property :language src-block))
         (code (org-export-format-code-default src-block info))
         (params (org-element-property :parameters src-block))
         (tangle (when params
                   (when (string-match ":tangle\\s-+\\([^[:space:]]+\\)" params)
                     (match-string 1 params)))))
    (if (and tangle (not (string= tangle "no")))
        (format "```%s\n;; → %s\n%s```" (or lang "") tangle code)
      (format "```%s\n%s```" (or lang "") code))))

(defun my-md-example-block (example-block _contents info)
  "Transcode EXAMPLE-BLOCK to fenced code block."
  (format "```\n%s```"
          (org-export-format-code-default example-block info)))

;; Override the md backend transcoders
(org-export-define-derived-backend 'md-fenced 'md
  :translate-alist '((src-block . my-md-src-block)
                     (example-block . my-md-example-block)))

;; Configure attachment handling
(setq org-attach-id-dir "/Users/adriandanao/git/org/personal/data/"
      org-attach-use-inheritance t)

;; Minimal config for clean export
(setq org-export-with-toc nil
      org-export-with-section-numbers nil
      org-export-with-author nil
      org-export-with-creator nil
      org-export-with-date nil
      org-export-with-timestamps nil
      org-export-with-todo-keywords nil
      org-export-with-priority nil
      org-export-preserve-breaks nil
      org-export-with-broken-links 'mark  ; Don't abort on unresolved ID links
      org-export-with-sub-superscripts nil  ; Don't interpret _ as subscript
      org-export-with-latex nil  ; Don't process LaTeX (avoid \( \) becoming $)
      org-md-headline-style 'atx)

(defun org--get-filetags ()
  "Extract filetags from current buffer."
  (save-excursion
    (goto-char (point-min))
    (when (re-search-forward "^#\\+filetags:\\s-*\\(.*\\)$" nil t)
      (let ((tags-str (match-string 1)))
        (delete "" (split-string tags-str ":"))))))

(defun org--get-id ()
  "Extract ID property from current buffer."
  (save-excursion
    (goto-char (point-min))
    (when (re-search-forward "^\\s-*:ID:\\s-*\\(.*\\)$" nil t)
      (string-trim (match-string 1)))))

(defun org--get-date ()
  "Extract #+DATE from current buffer."
  (save-excursion
    (goto-char (point-min))
    (when (re-search-forward "^#\\+[Dd][Aa][Tt][Ee]:\\s-*\\(.*\\)$" nil t)
      (string-trim (match-string 1)))))

(defun org--strip-links (text)
  "Remove org link markup from TEXT, keeping descriptions."
  (when text
    ;; [[url][desc]] -> desc
    (setq text (replace-regexp-in-string "\\[\\[[^]]+\\]\\[\\([^]]+\\)\\]\\]" "\\1" text))
    ;; [[url]] -> url
    (setq text (replace-regexp-in-string "\\[\\[\\([^]]+\\)\\]\\]" "\\1" text)))
  text)

(defun org-to-md (input-file output-file)
  "Export INPUT-FILE to OUTPUT-FILE as markdown with YAML frontmatter."
  (with-temp-buffer
    (insert-file-contents input-file)
    (org-mode)
    ;; Extract metadata
    (let* ((title (org--strip-links (or (org-get-title) (file-name-base input-file))))
           (id (org--get-id))
           (date (org--get-date))
           (tags (org--get-filetags))
           ;; Export body to markdown with fenced code blocks
           (content (org-export-as 'md-fenced nil nil t)))
      ;; Write frontmatter + content
      (with-temp-file output-file
        (insert "---\n")
        (insert (format "title: \"%s\"\n" (replace-regexp-in-string "\"" "\\\\\"" title)))
        (when id
          (insert (format "id: \"%s\"\n" id)))
        (when date
          (insert (format "date: %s\n" date)))
        (when tags
          (insert (format "tags:\n"))
          (dolist (tag tags)
            (insert (format "  - %s\n" tag))))
        (insert "---\n\n")
        (insert content))
      (message "Exported: %s" (file-name-nondirectory input-file)))))

(defun batch-export ()
  "Export files from command line: -- input1.org output1.md input2.org output2.md"
  (let ((args command-line-args-left))
    (while args
      (let ((input (pop args))
            (output (pop args)))
        (when (and input output (file-exists-p input))
          (condition-case err
              (org-to-md input output)
            (error (message "Error: %s - %s" input (error-message-string err)))))))))

(defun batch-export-from-file (batch-file)
  "Export files listed in BATCH-FILE (tab-separated: input<TAB>output per line)."
  (let ((count 0)
        (errors 0))
    (with-temp-buffer
      (insert-file-contents batch-file)
      (goto-char (point-min))
      (while (not (eobp))
        (let* ((line (buffer-substring-no-properties (line-beginning-position) (line-end-position)))
               (parts (split-string line "\t")))
          (when (= (length parts) 2)
            (let ((input (nth 0 parts))
                  (output (nth 1 parts)))
              (condition-case err
                  (progn
                    (org-to-md input output)
                    (setq count (1+ count)))
                (error
                 (setq errors (1+ errors))
                 (message "Error: %s" (error-message-string err)))))))
        (forward-line 1)))
    (message "Batch export complete: %d succeeded, %d failed" count errors)))

(provide 'export)
;;; export.el ends here
