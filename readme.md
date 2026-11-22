# MEB Access

An NVDA add-on that makes the Windows app **MEB: Mobile E-Books** (Meb.exe) usable with a screen reader.

Out of the box, Meb works with NVDA only partly:

* Most of its buttons have no names.
* Books open only with a mouse click.
* The side menu can't be reached with Tab.
* Meb's own contents list jumps to a chapter as soon as you arrow onto it.

This add-on fixes those gaps and adds reading commands.

## Requirements

* NVDA 2026.1 or later.
* MEB: Mobile E-Books for Windows. Tested with version 2.0.50; other versions may need updates to this add-on.
* Nothing else. Image (PDF) books need an OCR engine. The add-on offers to download it the first time you need it, or uses the one in the [Tesseract OCR add-on](https://github.com/ruifontes/tesseractOCR) if you have it. Windows' built-in OCR has no Thai, so NVDA's own OCR can't be used.

## Choose ePub, not PDF

The first time you open a book, Meb asks whether to download it as PDF or ePub. **Choose ePub.** ePub books contain real text that NVDA reads directly in browse mode. PDF books are page images that can only be read with OCR, which is slower and less accurate.

## Keyboard commands

These work only while Meb is the active window. All of them can be changed in NVDA's Input Gestures dialog, in the "MEB e-book reader" category.

### Bookshelf

Each book is one item, spoken as its title, download status and reading progress, for example "การสูญพันธุ์ครั้งที่ 6, 3%".

* Up and Down arrows (or Left and Right): previous or next book.
* Home / End: first or last book.
* Enter or Space: open the book.
* Applications key or Shift+F10: Meb's menu for the book (mark as finished, share, review, move to My Cloud, redownload, view in store).
* Alt+1: bookshelf.
* Alt+2: collections.
* Alt+3: My Cloud.
* Alt+4: news feed.
* Alt+5: notifications.
* Alt+S: search the MEB web store. Type what you're looking for; the results open in your web browser.

The add-on also announces search results (for example "ผลการค้นหา (3)"), when a book starts and finishes downloading, when syncing starts and finishes, and Meb's banner about books you may have finished.

### Reading ePub books

* Alt+T: move into the book text at the page Meb is showing, in browse mode, and read the first line. Use NVDA's normal reading keys from there; say all reads to the end of the chapter.
* When say all reaches the end of a chapter, the add-on moves to the next chapter and keeps reading.
* Page Down / Page Up: next or previous page; the browse mode cursor follows Meb's page.
* Control+Page Down / Control+Page Up: next or previous chapter, read from the top. Reading starts automatically if "Automatic Say All on page load" is on in NVDA's browse mode settings.
* Alt+C: chapter list. Choose a chapter and press Enter to go there.
* Alt+B: bookmark the current page.
* Alt+Shift+B: bookmark list. Press Enter to go to a bookmark, or Delete to remove it. Deleting asks for confirmation; Meb itself deletes bookmarks without asking.
* Alt+P: report the current chapter and page.
* Footnotes: press Enter on a footnote link (often shown as "[*]"). Meb opens the note in a message window, and NVDA reads it. Press Enter on OK to close it.

### Reading image (PDF) books

* Alt+T: read the current page with OCR. The result opens in NVDA's usual recognition window; press Escape to close it.
* The first time, if no OCR engine is installed, the add-on asks to download one. It's about 39 MB, downloaded once. You hear the progress, then "OCR engine installed"; press Alt+T again to read the page.
* Page Down / Page Up inside an OCR result: turn the page and read the new one.
* When say all reaches the end of an OCR page, the add-on turns the page and reads the next one.
* Pages you have already recognized are remembered until NVDA restarts, so going back is instant.

### Reporting a problem

* Alt+Shift+R: copy technical details about the focused control to the clipboard, to paste into a bug report. They can include book titles, so check them before sharing.

## Settings

In NVDA's Settings dialog, the "MEB Access" category has:

* Announce the page number when turning pages (on by default).
* Continue into the next chapter when say all reaches the end, in ePub books (on).
* Continue to the next page when say all reaches the end of an OCR page (on).
* Announce bookshelf changes: search results, downloads and sync (on).
* Remove zero-width spaces from speech (off). Thai ePub books put an invisible zero-width space between most words. Windows' Thai voice ignores them; if your voice pauses at every word, turn this on.
* OCR language for image books: Thai and English, Thai, or English.

## The MEB web store

Meb's store button opens the store website (mebmarket.com) in your browser, so this add-on can't change it. A check in November 2026 found:

* Book pages work well. The title is a heading, and the author, price, sample and buy buttons are all labelled.
* The site's own search can't be reached with the keyboard: the search icon is not focusable and the box stays hidden. Use Alt+S in Meb instead; it opens the search results page directly.
* The main menu opens only on mouse hover.
* On the home page, many book covers are links with no name. A rotating banner also adds about 30 "Go to slide" buttons to the Tab order.
* The page doesn't declare Thai as its language, so automatic language switching may not pick a Thai voice.
* Purchase and sign-in pages were not checked.

## Known limitations

* OCR works in Meb's left-right (paged) reading mode, not the vertical scrolling mode.
* OCR is about 98% accurate on normal Thai body text. Pages with only one or two lines, such as chapter endings, are less accurate and may include one garbled line.
* If you use Meb's own contents list instead of Alt+C, moving through it with the arrow keys jumps to each chapter and closes the list. That is how Meb behaves.
* Shelf positions ("3 of 12") are spoken only when Meb has loaded every book. With a long shelf, Meb loads only the books near the screen.
* Some button names are inferred from their position, because Meb gives them no identifier. Please report any button that is named wrongly.
* Meb updates can rename its internal controls. If labels disappear after a Meb update, please report it with Alt+Shift+R.

## The OCR engine

OCR uses [Tesseract](https://github.com/tesseract-ocr/tesseract), an open-source engine that runs on your computer. The add-on looks for it in this order:

1. The Tesseract OCR add-on, if it's installed and has data for the OCR language you chose.
2. A copy the add-on downloaded earlier.
3. If neither exists, the add-on asks whether to download one.

The download comes from two places, both pinned to a fixed version and checked against a known SHA-256 checksum before anything is installed:

* The Tesseract engine and English data, taken from the [Tesseract OCR add-on's](https://github.com/ruifontes/tesseractOCR) release package (version 2026.06.16, as listed in NVDA's Add-on Store). Only the engine is used; the other add-on is not installed.
* Thai data from the official [tessdata](https://github.com/tesseract-ocr/tessdata) repository.

The engine is stored in your NVDA settings folder (`mebAccess\tesseract`), so add-on updates keep it. Uninstalling MEB Access removes it.

## Privacy and copyright

The add-on only reads what Meb already shows on screen. It does not copy, export or decrypt books. OCR runs entirely on your computer: page images are passed straight to Tesseract and are never saved or sent anywhere. The only network access is the one-time OCR engine download, and only after you agree to it. It sends no information about you or your books.

## Building and contributing

The add-on uses the [NVDA add-on template](https://github.com/nvaccess/AddonTemplate). Every push to master builds it on GitHub Actions; the package can be downloaded from the run's artifacts. Pushing a version tag (for example `v1.0.1`, matching `addon_version` in `buildVars.py`) publishes a GitHub release.

To build locally you need [uv](https://docs.astral.sh/uv/) and the GNU gettext tools:

* `uv sync` installs the build tools.
* `uv run scons` builds `mebAccess-<version>.nvda-addon`.
* `uv run python tests/check_meb.py` runs the self-check on Windows. Add `--network` to also download the pinned OCR engine and test Thai OCR with it.
* `uv run prek run --all-files` runs the same code checks as CI.

The Thai translation is in `addon/locale/th/LC_MESSAGES/nvda.po`. The self-check fails if a message is untranslated.

## License

GNU General Public License, version 2. See COPYING.txt.
