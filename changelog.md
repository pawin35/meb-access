MEB Access 1.1.0, an NVDA add-on for the Windows app **MEB: Mobile E-Books**.

Requires NVDA 2026.1 or later. Tested with Meb 2.0.50 and NVDA 2026.3.

To install, download `mebAccess-1.1.0.nvda-addon` below and open it; NVDA asks to install it and restarts.

## New in 1.1.0

* Thai books put an invisible zero-width space between almost every word. In Meb's reading pane these are now hidden: they're left out of speech, braille and copied text, and the cursor no longer stops on them when you move by character or word. Previously some voices paused at every word, braille showed the spaces, and moving by character stopped silently between words.
* The text itself is unchanged, so the cursor, selection and braille routing keys still line up with the book.
* This is on by default. You can turn it off in NVDA's Settings, under "MEB Access".

## Features

* Names Meb's unlabeled buttons, in English or Thai depending on NVDA's language.
* Bookshelf: each book is one list item with its title, download status and reading progress. Move with the arrow keys, open with Enter, and use the Applications key for Meb's book menu. Alt+1 to Alt+5 go to the side menu sections.
* Announces search results, downloads, sync and Meb's "finished books" banner.
* ePub books: Alt+T starts reading at Meb's current page. Say all continues into the next chapter. Page Down and Page Up follow Meb's pages, and Control+Page Down and Control+Page Up change chapter.
* Chapter list (Alt+C), bookmarks (Alt+B to add, Alt+Shift+B to list, go to or delete), and footnotes read aloud.
* Image (PDF) books: offline Thai and English OCR with Tesseract (Alt+T). Say all continues to the next page, and recognized pages are remembered. The OCR engine is offered as a one-time download if it isn't installed.
* Alt+S searches the MEB web store, Alt+Shift+R copies diagnostics for bug reports, and settings are in NVDA's Settings dialog under "MEB Access".

See the readme for all commands and known limitations.
