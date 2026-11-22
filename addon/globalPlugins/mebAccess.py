# MEB Access: NVDA add-on for "MEB: Mobile E-Books" (Meb.exe, WPF, tested against 2.0.50).
# Labels the controls Meb leaves unnamed, makes the shelf and books keyboard-usable, and adds reading
# commands: page/chapter navigation, resume at Meb's page, continuous reading, chapter and bookmark
# lists, footnotes, offline Thai OCR for image books, shelf announcements and a settings panel.
# A global plugin rather than an app module because the ePub text lives in msedgewebview2.exe,
# where Meb's app module never sees key presses. Everything is gated on Meb being in front.
# Copyright (C) 2026 MEB Access contributors. Released under GNU GPL v2; see LICENSE.
import ctypes
import hashlib
import io
import os
import re
import shutil
import subprocess
import threading
import urllib.parse
import urllib.request
import zipfile
from collections import OrderedDict
from ctypes import wintypes

import addonHandler
import api
import buildVersion
import config
import controlTypes
import core
import eventHandler
import globalPluginHandler
import globalVars
import gui
import mouseHandler
import speech
import textInfos
import ui
import UIAHandler
import winUser
import winVersion
import wx
from comtypes import COMError
from contentRecog import ContentRecognizer, SimpleTextResult, recogUi
from gui import guiHelper, settingsDialogs
from gui.message import MessageDialog, ReturnCode
from logHandler import log
from NVDAObjects.behaviors import Dialog
from NVDAObjects.UIA import UIA
from scriptHandler import script
from speech import sayAll
from speech.extensions import filter_speechSequence

try:
	addonHandler.initTranslation()
except addonHandler.AddonError:
	pass  # loaded from the developer scratchpad: NVDA's built-in _() leaves strings untranslated

CONF = "mebAccess"
config.conf.spec[CONF] = {
	"announcePages": "boolean(default=True)",
	"continueChapters": "boolean(default=True)",
	"continueOcrPages": "boolean(default=True)",
	"announceShelf": "boolean(default=True)",
	"ocrLanguage": 'option("tha+eng", "tha", "eng", default="tha+eng")',
	# Thai ePubs put a zero-width space between words; some voices read or pause on each one.
	"stripZeroWidthSpaces": "boolean(default=True)",
}

STORE_SEARCH_URL = "https://www.mebmarket.com/index.php?action=search_book&search="
ZWSP = chr(0x200B)

# OCR engine downloaded on request when no usable Tesseract is installed. Tesseract publishes no portable
# Windows build, so this takes the one inside the Tesseract OCR add-on's package (the exact release NVDA's
# Add-on Store lists, checksum from the store) and Thai data from the official tessdata repository, pinned
# to a commit. Both are checked by SHA-256. Bump these together and run check_meb.py --network.
ENGINE_BUNDLE = {
	"url": "https://github.com/ruifontes/tesseractOCR/releases/download/2026.06.16/tesseractOCR-2026.06.16.nvda-addon",
	"sha256": "442e0af159d74edb3091e4af5b2b9c461d51664697dd8ca27a01cb6d19da3bc3",
	"prefix": "libs/tesseract64/",
	"keepData": ("eng",),  # the bundle's other data (osd) isn't used
}
EXTRA_TESSDATA = {
	"tha": (
		"https://raw.githubusercontent.com/tesseract-ocr/tessdata/cdd8a9ec438fc0b9f21635466196fe1c05efca16/tha.traineddata",
		"88032a9f21accff825efaed29604eb8a534e265cf8058a95ea5417a6df91c005",
	),
}
ENGINE_DOWNLOAD_MB = 39

# UI Automation ids (numeric: not all are re-exported by UIAHandler in NVDA 2026).
PROP_CONTROL_TYPE = 30003
PROP_NAME = 30005
PROP_AUTOMATION_ID = 30011
PROP_CLASS_NAME = 30012
PROP_IS_OFFSCREEN = 30022
TYPE_BUTTON = 50000
TYPE_LIST_ITEM = 50007
TYPE_TEXT = 50020
TYPE_DOCUMENT = 50030
SCOPE_CHILDREN = 2
SCOPE_DESCENDANTS = 4

# AutomationId -> label, for controls that have neither a name nor text inside.
LABELS = {
	# Translators: Label of Meb's settings button.
	"SettingButton": _("Settings"),
	# Translators: Label of a button that goes back to the previous screen.
	"BackButton": _("Back"),
	# Translators: Label of the search box on the bookshelf.
	"TextBoxSearch": _("Search my books"),
	# Translators: Label of the button that filters bookshelf search results.
	"SearchFilterButton": _("Search filter"),
	# Translators: Label of the button that selects every book while managing books.
	"SelectAllManageBookButton": _("Select all"),
	# Translators: Label of the button that stops a book download.
	"StopDownloadBtn": _("Stop download"),
	# Translators: Label of the button that downloads a book to this computer.
	"DownloadBookBtn": _("Download"),
	# Translators: Label of the window's minimize button.
	"MiniMizeButton": _("Minimize"),
	# Translators: Label of the window's maximize button.
	"MaximizeButton": _("Maximize"),
	# Translators: Label of a close button (window, dialog or list).
	"CloseButton": _("Close"),
	# Translators: Label of the reader's next page button.
	"PART_NextButton": _("Next page"),
	# Translators: Label of the reader's previous page button.
	"PART_PreviousButton": _("Previous page"),
	# Translators: Label of the reader's next page button.
	"NextPageButton": _("Next page"),
	# Translators: Label of the reader's previous page button.
	"PreviousPageButton": _("Previous page"),
	# Translators: Label of the reader's media (audio) button.
	"MediaButton": _("Media"),
	# Translators: Label of the reader's zoom slider.
	"ZoomSlider": _("Zoom"),
	# Translators: Label of a slider's decrease button.
	"DecreaseLarge": _("Decrease"),
	# Translators: Label of a slider's increase button.
	"IncreaseLarge": _("Increase"),
}

# Buttons whose inner text is the current value rather than a label (keyed by button or text AutomationId).
VALUE_PREFIXES = {
	# Translators: Spoken before the bookshelf's current sort order, e.g. "Sort by: recent activity".
	"SortByButton": _("Sort by"),
	# Translators: Spoken before the bookshelf's current cover style.
	"ShelfModeButton": _("Cover style"),
	# Translators: Spoken before the reader's current colour theme.
	"ThemeButtonLabel": _("Theme"),
	# Translators: Spoken before the reader's current reading mode (paged left-right or scrolling).
	"ReadModeLabel": _("Reading mode"),
	"ReadModeGridLabel": _("Reading mode"),
	# Translators: Spoken before the reader's current page layout (single or double page).
	"DoublePageModeLabel": _("Page layout"),
	# Translators: Spoken before how the page is fitted to the window.
	"FitSizeModeLabel": _("Fit"),
	# Translators: Spoken before the ePub reader's current font.
	"FontStyleLabel": _("Font"),
	# Translators: Spoken before the ePub reader's current font size.
	"FontSizeLabel": _("Font size"),
}

BOOK_STATES = {
	# Translators: Part of a bookshelf item: the book isn't on this computer yet.
	"notDownloaded": _("not downloaded"),
	# Translators: Part of a bookshelf item: the book is downloading now.
	"downloading": _("downloading"),
	# Translators: Part of a bookshelf item: the book is queued for download.
	"waiting": _("waiting to download"),
}

# Meb is Thai-only; "of" and "/" are there in case an English UI ever appears.
_PAGE_RE = re.compile(r"(\d+)\s*(?:จาก|of|/)\s*(\d+)")


def _conf(key):
	return config.conf[CONF][key]


# ---- pure logic (covered by check_meb.py) ----


def labelFor(aid, text, textId, prevAids, nextAid, topLeft, listItemButton=None):
	"""Spoken name for an unnamed control, from its AutomationId, inner text and neighbours.
	listItemButton: index among the unnamed buttons of a bookmark list item (pencil, then bin)."""
	if text == "X":  # Meb's close buttons show a bare letter
		text = ""
	prefix = VALUE_PREFIXES.get(aid) or VALUE_PREFIXES.get(textId)
	if prefix and text:
		return f"{prefix}: {text}"
	if text:
		return text
	if aid in LABELS:
		return LABELS[aid]
	if listItemButton == 0:
		# Translators: Label of the pencil button that renames a bookmark.
		return _("Rename bookmark")
	if listItemButton == 1:
		# Translators: Label of the bin button that deletes a bookmark.
		return _("Delete bookmark")
	if nextAid == "BookTitle" or (not aid and topLeft):
		return LABELS["BackButton"]
	if nextAid == "ZoomSlider":
		# Translators: Label of the reader's zoom out button.
		return _("Zoom out")
	if prevAids[:1] == ["ZoomSlider"]:
		# Translators: Label of the reader's zoom in button.
		return _("Zoom in")
	return ""


def parseShelf(infos):
	"""Books from the shelf list's children, given as (aid, controlType, name, offscreen) in order.
	Returns [{title, state, extras, cover, anchor}], cover/anchor being indexes into infos.
	Each book is: title text, images, cover (BrushOne), status texts and buttons, then its
	always-focusable "more options" button (the anchor this add-on uses as the book's focus stop)."""
	books, cur = [], None
	for i, (aid, ctype, name, offscreen) in enumerate(infos):
		name = name.strip()
		if aid == "BrushOne":
			title = ""
			for j in range(i - 1, max(i - 4, -1), -1):
				if infos[j][1] == TYPE_TEXT and infos[j][2].strip():
					title = infos[j][2].strip()
					break
			cur = {"title": title, "state": "", "extras": [], "cover": i}
		elif cur is None:
			continue
		elif ctype == TYPE_BUTTON and not aid:
			cur["anchor"] = i
			books.append(cur)
			cur = None
		elif not offscreen:
			if aid == "DownloadBookBtn":
				cur["state"] = "notDownloaded"
			elif aid == "StopDownloadBtn":
				cur["state"] = "downloading"
			elif ctype == TYPE_TEXT and name == "Waiting...":
				cur["state"] = cur["state"] or "waiting"
			elif ctype == TYPE_TEXT and name:
				cur["extras"].append(name)
	return books


def bookName(book):
	state = [BOOK_STATES[book["state"]]] if book["state"] else []
	return ", ".join([book["title"]] + state + book["extras"])


def headerCount(header):
	"""Book count from the shelf header, e.g. 'หนังสือทั้งหมด (2)' -> 2."""
	m = re.search(r"\((\d+)\)\s*$", header)
	return int(m.group(1)) if m else None


def shelfChanges(old, new):
	"""Messages for what changed between two shelf snapshots (see GlobalPlugin._shelfSnapshot)."""
	msgs = []
	if new["header"] != old["header"]:
		msgs.append(new["header"])
	if new["syncing"] and not old["syncing"]:
		msgs.append(new["syncText"])
	elif old["syncing"] and not new["syncing"]:
		# Translators: Reported when Meb finishes syncing the bookshelf with its server.
		msgs.append(_("Sync finished"))
	if new["banner"] and not old["banner"]:
		# Translators: Reported when Meb shows its banner about books that may be finished.
		msgs.append(new["bannerText"] or _("Meb found books you may have finished"))
	for title, state in new["books"].items():
		before = old["books"].get(title)
		if before is None or before == state:
			continue
		if state == "downloading":
			# Translators: Reported when a book starts downloading. {title} is the book title.
			msgs.append(_("Downloading {title}").format(title=title))
		elif not state and before in ("downloading", "waiting"):
			# Translators: Reported when a book finishes downloading. {title} is the book title.
			msgs.append(_("{title} downloaded").format(title=title))
	return msgs


def readerStatus(texts):
	"""(chapter, pageText, page, pages) from the reader frame's (controlType, name) children, or None.
	ePub shows '<chapter>', ' - ', 'หน้า X จาก Y'; image books show only the page text."""
	for i, (ctype, name) in enumerate(texts):
		m = ctype == TYPE_TEXT and _PAGE_RE.search(name)
		if m:
			chapter = texts[i - 2][1].strip() if i >= 2 and texts[i - 1][1].strip() == "-" else ""
			return chapter, name.strip(), int(m.group(1)), int(m.group(2))
	return None


def isNewChapter(start, prev, cur, forward=True):
	"""Whether status `cur` (from readerStatus) is in a different chapter than `start`,
	having stepped from `prev` in the given direction."""
	pageWentBack = cur[2] < prev[2] if forward else cur[2] > prev[2]
	return cur[0] != start[0] or cur[3] != start[3] or pageWentBack


def pickPage(rects, frame):
	"""Index of the largest rect (left, top, right, bottom) whose centre lies inside frame, or None."""
	best, bestArea = None, 0
	for i, (left, top, right, bottom) in enumerate(rects):
		cx, cy = (left + right) // 2, (top + bottom) // 2
		area = (right - left) * (bottom - top)
		if frame[0] <= cx < frame[2] and frame[1] <= cy < frame[3] and area > bestArea:
			best, bestArea = i, area
	return best


def textPoint(rect, host):
	"""Screen point on the first visible line of an ePub text node. Meb lays chapters out in columns,
	one per page; a paragraph continued from the previous page has a box starting left of the view,
	and its visible part is the top line of the current column, so aim at that line's right end."""
	left, top, right, bottom = rect
	return (right - 10 if left < host[0] else left + 3), top + 3


def stripZwsp(sequence):
	return [item.replace(ZWSP, "") if isinstance(item, str) else item for item in sequence]


def ocrLangs():
	return tuple(_conf("ocrLanguage").split("+"))


def tesseractCommand(exe, langs):
	"""Command line that reads a PNG on stdin and writes the text to stdout (book pages never touch disk)."""
	tessdata = os.path.join(os.path.dirname(exe), "tessdata")
	# psm 6 (one text block) at 1x scale scored best on Thai body text (~98% with 4+ lines); upscaling hurt.
	# ponytail: pages with only 1-2 lines (chapter ends) drop to ~85% and may gain a garbled line from the
	# raised vowel marks; --psm 4 fixes those but loses on full pages. Pick per line count if that matters.
	# preserve_interword_spaces stops Tesseract putting a space between every Thai character.
	return [
		exe,
		"stdin",
		"stdout",
		"--tessdata-dir",
		tessdata,
		"-l",
		"+".join(langs),
		"--psm",
		"6",
		"-c",
		"preserve_interword_spaces=1",
	]


def missingOcrLangs(exe, langs):
	tessdata = os.path.join(os.path.dirname(exe), "tessdata")
	return [lang for lang in langs if not os.path.isfile(os.path.join(tessdata, lang + ".traineddata"))]


def cleanOcrText(text):
	# Tesseract writes SARA AM as NIKHAHIT + SARA AA; synthesizers read the composed character better.
	return text.replace(chr(0x0E4D) + chr(0x0E32), chr(0x0E33)).strip()


def pixelsToImage(pixels, width, height):
	"""PIL grayscale image from NVDA's BGRA capture buffer."""
	from PIL import Image

	return Image.frombytes("RGB", (width, height), bytes(pixels), "raw", "BGRX").convert("L")


def verified(data, sha256):
	if hashlib.sha256(data).hexdigest() != sha256:
		raise ValueError("downloaded file failed its checksum")
	return data


def installEngine(target, download, progress=None):
	"""Download the OCR engine and unpack it into the folder target. download(url, progress) -> bytes.
	Works in a temporary folder and swaps it in only when everything checked out; raises on any failure."""
	tmp = target + ".partial"
	shutil.rmtree(tmp, ignore_errors=True)
	try:
		bundle = verified(download(ENGINE_BUNDLE["url"], progress), ENGINE_BUNDLE["sha256"])
		prefix = ENGINE_BUNDLE["prefix"]
		keep = {f"tessdata/{lang}.traineddata" for lang in ENGINE_BUNDLE["keepData"]}
		root = os.path.abspath(tmp) + os.sep
		with zipfile.ZipFile(io.BytesIO(bundle)) as z:
			for info in z.infolist():
				name = info.filename.replace("\\", "/")
				rel = name[len(prefix) :]
				if (
					info.is_dir()
					or not name.startswith(prefix)
					or (rel.startswith("tessdata/") and rel not in keep)
				):
					continue
				dest = os.path.abspath(os.path.join(tmp, *rel.split("/")))
				if not dest.startswith(root):
					raise ValueError(f"unsafe path in download: {name}")
				os.makedirs(os.path.dirname(dest), exist_ok=True)
				with z.open(info) as src, open(dest, "wb") as out:
					shutil.copyfileobj(src, out)
		for lang, (url, sha256) in EXTRA_TESSDATA.items():
			data = verified(download(url, None), sha256)
			with open(os.path.join(tmp, "tessdata", lang + ".traineddata"), "wb") as out:
				out.write(data)
		if not os.path.isfile(os.path.join(tmp, "tesseract.exe")):
			raise ValueError("tesseract.exe missing from download")
		shutil.rmtree(target, ignore_errors=True)
		os.replace(tmp, target)
	finally:
		shutil.rmtree(tmp, ignore_errors=True)


def _download(url, progress=None):
	"""Fetch url; progress(percent) is called at 25, 50 and 75%. Sends no user information."""
	request = urllib.request.Request(url, headers={"User-Agent": "MEB-Access-NVDA-add-on"})
	with urllib.request.urlopen(request, timeout=60) as response:
		total = int(response.headers.get("Content-Length") or 0)
		data, step = bytearray(), 1
		while chunk := response.read(256 * 1024):
			data += chunk
			if progress and total and step < 4 and len(data) * 4 >= total * step:
				progress(25 * step)
				step += 1
	return bytes(data)


class OcrCache(OrderedDict):
	"""Recognized page text for this NVDA session, most recently used last."""

	def __init__(self, limit=300):
		super().__init__()
		self.limit = limit

	def put(self, key, text):
		self[key] = text
		self.move_to_end(key)
		while len(self) > self.limit:
			self.popitem(last=False)


# ---- UI Automation helpers ----


def _client():
	return UIAHandler.handler.clientObject


def _cond(prop, value):
	return _client().CreatePropertyCondition(prop, value)


def _children(el):
	walker = _client().RawViewWalker
	child = walker.GetFirstChildElement(el)
	while child:
		yield child
		child = walker.GetNextSiblingElement(child)


def _siblings(el, backwards, limit):
	walker = _client().RawViewWalker
	step = walker.GetPreviousSiblingElement if backwards else walker.GetNextSiblingElement
	el = step(el)
	while el and limit:
		yield el
		el = step(el)
		limit -= 1


def _rawChildren(el):
	"""[(element, (aid, controlType, name, offscreen))] for el's raw children, in one cross-process call."""
	client = _client()
	request = client.CreateCacheRequest()
	for prop in (PROP_AUTOMATION_ID, PROP_CONTROL_TYPE, PROP_NAME, PROP_IS_OFFSCREEN, PROP_CLASS_NAME):
		request.AddProperty(prop)
	request.TreeFilter = client.RawViewCondition
	found = el.FindAllBuildCache(SCOPE_CHILDREN, client.RawViewCondition, request)
	result = []
	for i in range(found.Length):
		e = found.GetElement(i)
		result.append(
			(e, (e.CachedAutomationId, e.CachedControlType, e.CachedName, bool(e.CachedIsOffscreen))),
		)
	return result


def _rawFind(el, pred, depth=12):
	"""First raw descendant matching pred, not descending into hosted web content."""
	for child in _children(el):
		if pred(child):
			return child
		if depth and child.CurrentClassName != "HwndHost":
			found = _rawFind(child, pred, depth - 1)
			if found:
				return found
	return None


def _rect(el):
	r = el.CurrentBoundingRectangle
	return (r.left, r.top, r.right, r.bottom)


def _child(el, *aids):
	for aid in aids:
		found = el.FindFirst(SCOPE_CHILDREN, _cond(PROP_AUTOMATION_ID, aid))
		if found:
			return found
	return None


def _rawChild(el, aid):
	return next((c for c in _children(el) if c.CurrentAutomationId == aid), None)


def _firstText(el):
	"""(name, AutomationId) of the first named text inside el."""
	found = el.FindAll(SCOPE_DESCENDANTS, _cond(PROP_CONTROL_TYPE, TYPE_TEXT))
	for i in range(found.Length):
		t = found.GetElement(i)
		if t.CurrentName.strip():
			return t.CurrentName.strip(), t.CurrentAutomationId
	return "", ""


def _invoke(el):
	el.GetCurrentPattern(UIAHandler.UIA_InvokePatternId).QueryInterface(
		UIAHandler.IUIAutomationInvokePattern,
	).Invoke()


def _select(el):
	el.GetCurrentPattern(UIAHandler.UIA_SelectionItemPatternId).QueryInterface(
		UIAHandler.IUIAutomationSelectionItemPattern,
	).Select()


def _click(el):
	left, top, right, bottom = _rect(el)
	winUser.setCursorPos((left + right) // 2, top + (bottom - top) // 3)
	mouseHandler.doPrimaryClick()


def _toNVDAObject(el):
	return UIA(UIAElement=el.BuildUpdatedCache(UIAHandler.handler.baseCacheRequest))


_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _mebWindows():
	"""UIA elements of Meb's visible top-level windows. Meb's popups (contents, bookmarks, toolbar)
	are separate windows that don't reliably appear under the main window in the UIA tree."""
	fg = api.getForegroundObject()
	if not _isMeb(fg):
		return []
	hwnds = []

	def collect(hwnd, lParam):
		if winUser.isWindowVisible(hwnd) and winUser.getWindowThreadProcessID(hwnd)[0] == fg.processID:
			hwnds.append(hwnd)
		return True

	ctypes.windll.user32.EnumWindows(_WNDENUMPROC(collect), 0)
	return [_client().ElementFromHandle(h) for h in hwnds]


def _findInMeb(pred):
	for window in _mebWindows():
		found = window if pred(window) else _rawFind(window, pred)
		if found:
			return found
	return None


def _listItems(popup):
	listBox = _rawChild(popup, "ListBox")
	return list(_children(listBox)) if listBox else []


def _itemText(item):
	return next((c.CurrentName.strip() for c in _children(item) if c.CurrentControlType == TYPE_TEXT), "")


def _ownEngineDir():
	# In NVDA's config folder, not the add-on's: NVDA replaces the add-on folder on every update.
	return os.path.join(globalVars.appArgs.configPath, "mebAccess", "tesseract")


def _findEngine(langs):
	"""tesseract.exe with data for langs: the Tesseract OCR add-on's if it has them, else MEB Access's own."""
	candidates = [
		os.path.join(addon.path, "globalPlugins", "tesseractOCR", "tesseract", "tesseract.exe")
		for addon in addonHandler.getRunningAddons()
		if addon.name == "tesseractOCR"
	]
	candidates.append(os.path.join(_ownEngineDir(), "tesseract.exe"))
	return next((exe for exe in candidates if os.path.isfile(exe) and not missingOcrLangs(exe, langs)), None)


def _isMeb(obj):
	# Runs for every object and key press in every app: must never raise.
	return getattr(getattr(obj, "appModule", None), "appName", None) == "meb"


def _caretAtEnd(obj):
	"""Whether only blank text follows the caret's line in obj (a browse mode document or an OCR result).
	Chapters often end in whitespace-only nodes that say all doesn't stop on."""
	rest = obj.makeTextInfo(textInfos.POSITION_CARET)
	rest.expand(textInfos.UNIT_LINE)
	rest.collapse(end=True)
	rest.setEndPoint(obj.makeTextInfo(textInfos.POSITION_ALL), "endToEnd")
	return not rest.text.replace(ZWSP, "").strip()


def _waitFor(find, then, onTimeout=None, tries=20):
	"""Poll find() every 100 ms without blocking NVDA; call then(result) once it returns something."""
	try:
		found = find()
	except COMError:
		found = None
	if found:
		then(found)
	elif tries:
		core.callLater(100, _waitFor, find, then, onTimeout, tries - 1)
	elif onTimeout:
		onTimeout()


def _whenMebActive(action, tries=30):
	"""Run action once Meb is back in front (e.g. after one of our dialogs closes)."""
	_waitFor(lambda: _isMeb(api.getForegroundObject()), lambda found: action(), tries=tries)


# ---- NVDA objects ----


class MebControl(UIA):
	"""A Meb control without an accessible name."""

	def _get_name(self):
		try:
			el = self.UIAElement
			text, textId = _firstText(el)
			prevAids = [s.CurrentAutomationId for s in _siblings(el, True, 6)]
			nxt = next(_siblings(el, False, 1), None)
			nextAid = nxt.CurrentAutomationId if nxt else ""
			listItemButton = None
			parent = _client().RawViewWalker.GetParentElement(el)
			if parent and parent.CurrentControlType == TYPE_LIST_ITEM:
				buttons = [
					c for c in _children(parent) if c.CurrentControlType == TYPE_BUTTON and not c.CurrentName
				]
				listItemButton = next(
					(i for i, b in enumerate(buttons) if _client().CompareElements(b, el)),
					None,
				)
		except COMError:
			return super()._get_name()
		loc, fg = self.location, api.getForegroundObject().location
		topLeft = bool(loc and fg) and loc.left - fg.left < 120 and loc.top - fg.top < 120
		name = labelFor(self.UIAAutomationId, text, textId, prevAids, nextAid, topLeft, listItemButton)
		return name or super()._get_name()


class MebListItem(UIA):
	"""An item in Meb's contents or bookmark list, whose own name is blank."""

	def _get_name(self):
		try:
			return _itemText(self.UIAElement) or super()._get_name()
		except COMError:
			return super()._get_name()


class MebDialog(Dialog):
	"""Meb's message windows (footnotes and alerts): read their text when they open."""

	role = controlTypes.Role.DIALOG


class MebBook(UIA):
	"""A book on the shelf. Its "more options" button is the one part that is always focusable,
	so it stands in for the whole book: name, position, Enter to open, arrows to move."""

	role = controlTypes.Role.LISTITEM

	def _book(self):
		"""(books, elements, index of this book or None) for the shelf list holding this button."""
		parent = _client().RawViewWalker.GetParentElement(self.UIAElement)
		kids = _rawChildren(parent)
		books = parseShelf([info for el, info in kids])
		elements = [el for el, info in kids]
		for i, book in enumerate(books):
			if _client().CompareElements(elements[book["anchor"]], self.UIAElement):
				return books, elements, i
		return books, elements, None

	def _get_name(self):
		try:
			books, elements, i = self._book()
		except COMError:
			return super()._get_name()
		return bookName(books[i]) if i is not None else super()._get_name()

	def _get_positionInfo(self):
		try:
			books, elements, i = self._book()
			main = _client().RawViewWalker.GetParentElement(
				_client().RawViewWalker.GetParentElement(self.UIAElement),
			)
			header = _child(main, "TitleHeader")
			total = headerCount(header.CurrentName) if header else None
		except COMError:
			return {}
		# The shelf panel only creates items near the screen; positions are only right when all are loaded.
		if i is None or total != len(books):
			return {}
		return {"indexInGroup": i + 1, "similarItemsInGroup": total}

	@script(
		# Translators: Describes the command that opens the focused book.
		description=_("Open the focused book"),
		gestures=["kb:enter", "kb:space"],
	)
	def script_openBook(self, gesture):
		books, elements, i = self._book()
		cover = elements[books[i]["cover"]] if i is not None else None
		if cover is None or cover.CurrentIsOffscreen:
			# Translators: Reported when a book can't be opened because its cover is scrolled out of view.
			ui.message(_("Book cover is not visible"))
			return
		_click(cover)

	@script(
		# Translators: Describes the command that opens Meb's menu for the focused book.
		description=_("Open the focused book's menu (mark as finished, share, redownload...)"),
		gestures=["kb:applications", "kb:shift+f10"],
	)
	def script_bookMenu(self, gesture):
		self.doAction()

	def _moveTo(self, where):
		"""Focus another book: where is +1/-1 (relative), "first" or "last"."""
		books, elements, i = self._book()
		if i is None:
			return
		target = {"first": 0, "last": len(books) - 1}.get(where, i + where if isinstance(where, int) else i)
		if target < 0:
			# Translators: Reported when moving past the first book on the shelf.
			ui.message(_("First book"))
		elif target >= len(books):
			# Translators: Reported when moving past the last book on the shelf.
			ui.message(_("Last book"))
		elif target != i:
			elements[books[target]["anchor"]].SetFocus()

	@script(
		# Translators: Describes the command that moves to the next book on the shelf.
		description=_("Next book"),
		gestures=["kb:downArrow", "kb:rightArrow"],
	)
	def script_nextBook(self, gesture):
		self._moveTo(1)

	@script(
		# Translators: Describes the command that moves to the previous book on the shelf.
		description=_("Previous book"),
		gestures=["kb:upArrow", "kb:leftArrow"],
	)
	def script_previousBook(self, gesture):
		self._moveTo(-1)

	@script(
		# Translators: Describes the command that moves to the first book on the shelf.
		description=_("First book"),
		gesture="kb:home",
	)
	def script_firstBook(self, gesture):
		self._moveTo("first")

	@script(
		# Translators: Describes the command that moves to the last book on the shelf.
		description=_("Last book"),
		gesture="kb:end",
	)
	def script_lastBook(self, gesture):
		self._moveTo("last")


class TesseractRecognizer(ContentRecognizer):
	"""Offline OCR using the Tesseract binary shipped with the Tesseract OCR add-on."""

	def __init__(self, exe, langs, cached=None, store=None, autoSayAll=None):
		self.exe, self.langs, self.cached, self.store = exe, langs, cached, store
		self.autoSayAllOnResult = (
			config.conf["uwpOcr"]["autoSayAllOnResult"] if autoSayAll is None else autoSayAll
		)

	def recognize(self, pixels, imageInfo, onResult):
		threading.Thread(target=self._run, args=(pixels, imageInfo, onResult), daemon=True).start()

	def _run(self, pixels, imageInfo, onResult):
		if self.cached is not None:
			onResult(SimpleTextResult(self.cached))
			return
		try:
			png = io.BytesIO()
			pixelsToImage(pixels, imageInfo.recogWidth, imageInfo.recogHeight).save(png, "PNG")
			out = subprocess.run(
				tesseractCommand(self.exe, self.langs),
				input=png.getvalue(),
				capture_output=True,
				timeout=120,
				creationflags=subprocess.CREATE_NO_WINDOW,
			)
		except (OSError, subprocess.SubprocessError) as e:
			onResult(e)
			return
		if out.returncode:
			onResult(
				RuntimeError(f"tesseract exited {out.returncode}: {out.stderr.decode('utf-8', 'replace')}"),
			)
			return
		# Translators: Shown as the OCR result when a page has no recognizable text.
		text = cleanOcrText(out.stdout.decode("utf-8", "replace")) or _("No text found on this page")
		if self.store:
			self.store(text)
		onResult(SimpleTextResult(text))

	def cancel(self):
		pass


class _ListDialog(wx.Dialog):
	"""A list of chapters or bookmarks to jump to (and delete, for bookmarks)."""

	def __init__(self, title, label, items, selection, onChoose, onDelete=None):
		super().__init__(gui.mainFrame, title=title)
		self._items, self._onChoose, self._onDelete = items, onChoose, onDelete
		mainSizer = wx.BoxSizer(wx.VERTICAL)
		helper = guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)
		self.list = helper.addLabeledControl(label, wx.ListBox, choices=items)
		self.list.SetSelection(selection)
		buttons = guiHelper.ButtonHelper(wx.HORIZONTAL)
		# Translators: Button that jumps to the chapter or bookmark selected in the list.
		go = buttons.addButton(self, label=_("&Go to"))
		go.SetDefault()
		go.Bind(wx.EVT_BUTTON, self._choose)
		if onDelete:
			# Translators: Button that deletes the bookmark selected in the list.
			delete = buttons.addButton(self, label=_("&Delete"))
			delete.Bind(wx.EVT_BUTTON, self._delete)
			self.list.Bind(wx.EVT_KEY_DOWN, self._onKey)
		# Translators: Button that closes the chapter or bookmark list.
		close = buttons.addButton(self, id=wx.ID_CLOSE, label=_("&Close"))
		close.Bind(wx.EVT_BUTTON, lambda evt: self.Destroy())
		self.SetEscapeId(wx.ID_CLOSE)
		helper.addItem(buttons)
		mainSizer.Add(helper.sizer, border=guiHelper.BORDER_FOR_DIALOGS, flag=wx.ALL)
		self.SetSizerAndFit(mainSizer)
		self.CentreOnScreen()

	def show(self):
		gui.mainFrame.prePopup()
		self.Show()
		self.list.SetFocus()
		gui.mainFrame.postPopup()

	def _choose(self, evt):
		index = self.list.GetSelection()
		if index != wx.NOT_FOUND:
			self.Destroy()
			self._onChoose(index)

	def _delete(self, evt):
		index = self.list.GetSelection()
		if index == wx.NOT_FOUND:
			return
		answer = MessageDialog.confirm(
			# Translators: Asks before deleting a bookmark. {name} is the bookmark (chapter and percentage).
			_("Delete bookmark {name}?").format(name=self._items[index]),
			# Translators: Title of the confirmation before deleting a bookmark.
			_("Delete bookmark"),
			parent=self,
		)
		if answer == ReturnCode.OK:
			self.Destroy()
			self._onDelete(index)

	def _onKey(self, evt):
		if evt.GetKeyCode() == wx.WXK_DELETE:
			self._delete(evt)
		else:
			evt.Skip()


class MebSettingsPanel(settingsDialogs.SettingsPanel):
	# Translators: Title of this add-on's category in NVDA's settings dialog.
	title = _("MEB Access")

	def makeSettings(self, settingsSizer):
		helper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)
		self._checks = {}
		for key, label in (
			# Translators: A setting of the MEB Access add-on.
			("announcePages", _("Announce the &page number when turning pages")),
			# Translators: A setting of the MEB Access add-on.
			("continueChapters", _("Continue into the next &chapter when say all reaches the end (ePub)")),
			# Translators: A setting of the MEB Access add-on.
			("continueOcrPages", _("Continue to the next page when say all reaches the end of an &OCR page")),
			# Translators: A setting of the MEB Access add-on.
			("announceShelf", _("Announce &bookshelf changes (search results, downloads, sync)")),
			# Translators: A setting of the MEB Access add-on.
			(
				"stripZeroWidthSpaces",
				_("Remove the invisible &zero-width spaces between Thai words from speech"),
			),
		):
			box = helper.addItem(wx.CheckBox(self, label=label))
			box.SetValue(_conf(key))
			self._checks[key] = box
		self._langCodes = ["tha+eng", "tha", "eng"]
		# Translators: Choices for the OCR language setting.
		langNames = [_("Thai and English"), _("Thai"), _("English")]
		# Translators: Label of the OCR language setting.
		self._lang = helper.addLabeledControl(
			_("OCR &language for image books:"),
			wx.Choice,
			choices=langNames,
		)
		self._lang.SetSelection(self._langCodes.index(_conf("ocrLanguage")))

	def onSave(self):
		for key, box in self._checks.items():
			config.conf[CONF][key] = box.IsChecked()
		config.conf[CONF]["ocrLanguage"] = self._langCodes[self._lang.GetSelection()]


# ---- plugin ----


def _disabledInSecureMode(cls):
	return globalPluginHandler.GlobalPlugin if globalVars.appArgs.secure else cls


@_disabledInSecureMode
class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	# Translators: Category of this add-on's commands in NVDA's Input Gestures dialog.
	scriptCategory = _("MEB e-book reader")

	def __init__(self):
		super().__init__()
		self._shelf = None  # last shelf snapshot, for announcements
		self._sayAllWasRunning = False
		self._busy = False  # a chapter change is stepping through pages
		self._downloading = False  # the OCR engine is being downloaded
		self._ocrCache = OcrCache()
		self._timer = wx.PyTimer(self._tick)
		self._timer.Start(1000)
		filter_speechSequence.register(self._filterSpeech)
		settingsDialogs.NVDASettingsDialog.categoryClasses.append(MebSettingsPanel)

	def terminate(self):
		self._timer.Stop()
		filter_speechSequence.unregister(self._filterSpeech)
		settingsDialogs.NVDASettingsDialog.categoryClasses.remove(MebSettingsPanel)
		super().terminate()

	def chooseNVDAObjectOverlayClasses(self, obj, clsList):
		if not (isinstance(obj, UIA) and _isMeb(obj)):
			return
		role = obj.role
		try:
			if role in (controlTypes.Role.WINDOW, controlTypes.Role.DIALOG):
				if obj.UIAElement.CurrentName and any(
					info[0] == "TitleTextBlock" for el, info in _rawChildren(obj.UIAElement)
				):
					clsList.insert(0, MebDialog)
				return
			if role == controlTypes.Role.LISTITEM:
				if not obj.UIAElement.CurrentName.strip():
					clsList.insert(0, MebListItem)
				return
			if role not in (
				controlTypes.Role.BUTTON,
				controlTypes.Role.EDITABLETEXT,
				controlTypes.Role.SLIDER,
			):
				return
			name = obj.UIAElement.CurrentName  # raw value: obj.name would cache '' before our overlay applies
			aid = obj.UIAAutomationId
			if (
				role == controlTypes.Role.BUTTON
				and not name
				and not aid
				and any(
					s.CurrentAutomationId == "DownloadBookBtn" for s in _siblings(obj.UIAElement, True, 6)
				)
			):
				clsList.insert(0, MebBook)
			elif not name or name == "X":
				clsList.insert(0, MebControl)
		except COMError:
			return

	def getScript(self, gesture):
		# Our keys only exist while Meb is in front; everywhere else they're untouched.
		return super().getScript(gesture) if _isMeb(api.getForegroundObject()) else None

	def _filterSpeech(self, speechSequence, **kwargs):
		if _conf("stripZeroWidthSpaces") and _isMeb(api.getForegroundObject()):
			return stripZwsp(speechSequence)
		return speechSequence

	# -- Meb's screens --

	def _frame(self):
		"""Meb's MainFrame element (shelf or reader), or None if Meb isn't in front."""
		fg = api.getForegroundObject()
		if not _isMeb(fg):
			return None
		return _child(_client().ElementFromHandle(fg.windowHandle), "MainFrame")

	def _status(self, frame):
		return readerStatus([(c.CurrentControlType, c.CurrentName) for c in _children(frame)])

	def _sayStatus(self):
		frame = self._frame()
		st = frame and self._status(frame)
		if st:
			ui.message(f"{st[0]}, {st[1]}" if st[0] else st[1])
		return bool(st)

	# -- background monitor: shelf announcements and continuous reading --

	def _tick(self):
		if not _isMeb(api.getForegroundObject()):
			self._shelf = None
			self._sayAllWasRunning = False
			return
		try:
			self._checkSayAllEnd()
			self._checkShelf()
		except COMError:
			pass  # Meb changed screens in the middle of a check; the next tick catches up
		except Exception:
			# Runs every second: keep a surprise from Meb out of the user's log at normal levels.
			log.debugWarning("MEB Access monitor check failed", exc_info=True)

	def _checkSayAllEnd(self):
		running = sayAll.SayAllHandler.isRunning()
		ended = self._sayAllWasRunning and not running
		self._sayAllWasRunning = running
		if not ended or self._busy:
			return
		focus = api.getFocusObject()
		if isinstance(focus, recogUi.RecogResultNVDAObject):
			if _conf("continueOcrPages") and _caretAtEnd(focus):
				self._turnPage(None, True, continuous=True)
		elif _conf("continueChapters"):
			ti = focus.treeInterceptor
			if ti and ti.isReady and _caretAtEnd(ti):
				self._changeChapter(None, True, readAll=True)

	def _shelfSnapshot(self, main):
		kids = _rawChildren(main)
		byAid = {info[0]: (i, info) for i, (el, info) in enumerate(kids) if info[0]}
		if "TitleHeader" not in byAid:
			return None
		sync = byAid.get("SyncingBadgeText", (0, ("", 0, "", True)))[1]
		bannerIndex, banner = byAid.get("MarkAllFinishedBannerButton", (0, ("", 0, "", True)))
		listEl = next((el for el, info in kids if el.CachedClassName == "ScrollViewer" and not info[0]), None)
		books = parseShelf([info for el, info in _rawChildren(listEl)]) if listEl else []
		return {
			"header": byAid["TitleHeader"][1][2],
			"syncing": not sync[3],
			"syncText": sync[2],
			"banner": not banner[3],
			"bannerText": kids[bannerIndex - 1][1][2] if bannerIndex else "",
			"books": {b["title"]: b["state"] for b in books},
		}

	def _checkShelf(self):
		frame = self._frame()
		main = frame and _child(frame, "Main")
		snap = self._shelfSnapshot(main) if main else None
		if snap and self._shelf and _conf("announceShelf"):
			for msg in shelfChanges(self._shelf, snap):
				ui.message(msg)
		self._shelf = snap

	# -- ePub text --

	def _focusText(self, mode="page", readAll=False):
		"""Move into the ePub text (browse mode) and put the caret at the top of Meb's current page
		(mode "page") or of the chapter (mode "top"). False if this isn't the ePub reader."""
		frame = self._frame()
		host = frame and _child(frame, "webView2")
		doc = host and host.FindFirst(SCOPE_DESCENDANTS, _cond(PROP_CONTROL_TYPE, TYPE_DOCUMENT))
		if not doc:
			return False
		doc.SetFocus()
		core.callLater(300, self._placeCaret, host, doc, mode, readAll, 10)
		return True

	def _placeCaret(self, host, doc, mode, readAll, tries):
		ti = api.getFocusObject().treeInterceptor
		if not (ti and ti.isReady):
			if tries:
				core.callLater(200, self._placeCaret, host, doc, mode, readAll, tries - 1)
			return
		info = None
		if mode == "page":
			try:
				info = self._visibleTextInfo(ti, host, doc)
			except (COMError, LookupError, RuntimeError):
				info = None
		if info is None:
			info = ti.makeTextInfo(textInfos.POSITION_FIRST)
		info.collapse()
		ti.selection = info
		if readAll:
			sayAll.SayAllHandler.readText(sayAll.CURSOR.CARET)
		else:
			info.expand(textInfos.UNIT_LINE)
			speech.speakTextInfo(info, unit=textInfos.UNIT_LINE, reason=controlTypes.OutputReason.CARET)

	def _visibleTextInfo(self, ti, host, doc):
		"""Browse mode position of the first text Meb shows on screen. The whole chapter is in the page;
		text on other pages is scrolled sideways out of view and marked offscreen."""
		client = _client()
		visible = doc.FindAll(
			SCOPE_DESCENDANTS,
			client.CreateAndCondition(
				_cond(PROP_CONTROL_TYPE, TYPE_TEXT),
				_cond(PROP_IS_OFFSCREEN, False),
			),
		)
		for i in range(visible.Length):
			el = visible.GetElement(i)
			if el.CurrentName.strip():
				x, y = textPoint(_rect(el), _rect(host))
				obj = api.getDesktopObject().objectFromPoint(x, y)
				return ti.makeTextInfo(obj) if obj else None
		return None

	# -- image books --

	def _ocrPage(self, continuous=False):
		"""OCR the visible page of an image (PDF) book. False if no page image is showing."""
		frame = self._frame()
		if not frame:
			return False
		pages = [
			img
			for pane in _children(frame)
			if pane.CurrentAutomationId == "FlipViewScrollViewer"
			for img in _children(pane)
			if img.CurrentAutomationId == "ImageFlipView"
		]
		rects = [_rect(p) for p in pages]
		i = pickPage(rects, _rect(frame))
		if i is None:
			return False
		langs = ocrLangs()
		exe = _findEngine(langs)
		if not exe:
			self._offerEngineDownload()
			return True
		title = _child(frame, "BookTitle")
		st = self._status(frame)
		left, top, right, bottom = rects[i]
		key = (title.CurrentName if title else "", st[1] if st else "", right - left, bottom - top, langs)
		recognizer = TesseractRecognizer(
			exe,
			langs,
			cached=self._ocrCache.get(key),
			store=lambda text: self._ocrCache.put(key, text),
			autoSayAll=True if continuous else None,
		)
		api.setNavigatorObject(_toNVDAObject(pages[i]))
		recogUi.recognizeNavigatorObject(recognizer)
		return True

	def _offerEngineDownload(self):
		if self._downloading:
			# Translators: Reported when OCR is requested while the OCR engine is still downloading.
			ui.message(_("The OCR engine is still downloading"))
			return

		def ask():
			answer = MessageDialog.confirm(
				# Translators: Asks before downloading the OCR engine. {size} is the download size in megabytes.
				_(
					"Reading image books needs an OCR engine, which isn't installed yet. Download it now? "
					"It's about {size} MB, downloaded once from GitHub: the Tesseract engine with Thai and English data.",
				).format(size=ENGINE_DOWNLOAD_MB),
				# Translators: Title of the dialog that offers to download the OCR engine.
				_("MEB Access: OCR engine"),
				# Translators: Button that starts downloading the OCR engine.
				okLabel=_("&Download"),
			)
			if answer == ReturnCode.OK:
				self._startEngineDownload()

		wx.CallAfter(ask)

	def _startEngineDownload(self):
		self._downloading = True
		# Translators: Reported when the OCR engine download starts.
		ui.message(_("Downloading the OCR engine"))

		def say(text):
			wx.CallAfter(ui.message, text)

		def work():
			try:
				installEngine(_ownEngineDir(), _download, lambda percent: say(f"{percent}%"))
			except Exception as e:  # network, disk and checksum failures all end the same way for the user
				log.warning("MEB Access: OCR engine download failed", exc_info=True)
				# Translators: Reported when the OCR engine download fails. {error} is the reason.
				say(_("Couldn't download the OCR engine: {error}").format(error=e))
			else:
				# Translators: Reported when the OCR engine has been downloaded and installed.
				say(_("OCR engine installed. Press Alt+T to read the page."))
			finally:
				self._downloading = False

		threading.Thread(target=work, daemon=True).start()

	# -- pages and chapters --

	def _turnPage(self, gesture, forward, continuous=False):
		frame = self._frame()
		btn = frame and (
			_child(frame, "NextPageButton", "PART_NextButton")
			if forward
			else _child(frame, "PreviousPageButton", "PART_PreviousButton")
		)
		if not btn:
			if gesture:
				gesture.send()
			return
		focus = api.getFocusObject()
		inOcr = isinstance(focus, recogUi.RecogResultNVDAObject)
		if inOcr:
			eventHandler.executeEvent("gainFocus", focus.parent)
		inText = not inOcr and focus.treeInterceptor is not None
		before = self._status(frame)
		_invoke(btn)
		self._afterTurn(frame, before, inOcr, inText, continuous, 20)

	def _afterTurn(self, frame, before, ocr, inText, continuous, triesLeft):
		"""Act once Meb has updated its page number (or after ~2 s, e.g. on the last page)."""
		try:
			cur = self._status(frame)
		except COMError:  # reader was closed
			return
		if cur == before and triesLeft:
			core.callLater(100, self._afterTurn, frame, before, ocr, inText, continuous, triesLeft - 1)
			return
		if _conf("announcePages"):
			self._sayStatus()
		if ocr:
			core.callLater(500, self._ocrPage, continuous)  # give the new page image time to render
		elif inText:
			core.callLater(300, self._focusText, "page", False)  # follow Meb to the new page

	@script(
		# Translators: Describes the next page command.
		description=_(
			"Next page (in ePub text: move to the next page; in an OCR result: next page and recognize it)",
		),
		gesture="kb:pageDown",
	)
	def script_nextPage(self, gesture):
		self._turnPage(gesture, True)

	@script(
		# Translators: Describes the previous page command.
		description=_(
			"Previous page (in ePub text: move to the previous page; in an OCR result: previous page and recognize it)",
		),
		gesture="kb:pageUp",
	)
	def script_previousPage(self, gesture):
		self._turnPage(gesture, False)

	def _changeChapter(self, gesture, forward, readAll=None):
		frame = self._frame()
		btn = frame and _child(frame, "NextPageButton" if forward else "PreviousPageButton")
		st = btn and self._status(frame)
		if not st:
			if gesture:
				gesture.send()
			return
		if readAll is None:
			readAll = config.conf["virtualBuffers"]["autoSayAllOnPageLoad"]
		self._busy = True
		steps = (st[3] - st[2] if forward else st[2] - 1) + 3
		self._chapterStep(btn, frame, st, st, steps, forward, readAll)

	def _chapterStep(self, btn, frame, start, prev, left, forward, readAll):
		try:
			_invoke(btn)
		except COMError:  # reader was closed
			self._busy = False
			return
		core.callLater(300, self._chapterCheck, btn, frame, start, prev, left - 1, forward, readAll)

	def _chapterCheck(self, btn, frame, start, prev, left, forward, readAll):
		try:
			cur = self._status(frame)
		except COMError:
			self._busy = False
			return
		if cur and isNewChapter(start, prev, cur, forward):
			self._busy = False
			self._sayStatus()
			self._focusText("top", readAll)
		elif left > 0:
			self._chapterStep(btn, frame, start, cur or prev, left, forward, readAll)
		else:
			self._busy = False
			# Translators: Reported when there is no chapter after (or before) the current one.
			ui.message(_("No next chapter") if forward else _("No previous chapter"))

	@script(
		# Translators: Describes the next chapter command.
		description=_("ePub: go to the next chapter and start reading it"),
		gesture="kb:control+pageDown",
	)
	def script_nextChapter(self, gesture):
		self._changeChapter(gesture, True)

	@script(
		# Translators: Describes the previous chapter command.
		description=_("ePub: go to the previous chapter and start reading it"),
		gesture="kb:control+pageUp",
	)
	def script_previousChapter(self, gesture):
		self._changeChapter(gesture, False)

	@script(
		# Translators: Describes the command that moves into the book text or OCRs the page.
		description=_(
			"Read the book from Meb's current page: move into the ePub text, or OCR the page of an image book",
		),
		gesture="kb:alt+t",
	)
	def script_readText(self, gesture):
		if not (self._focusText("page") or self._ocrPage()):
			gesture.send()

	@script(
		# Translators: Describes the command that reports the current chapter and page.
		description=_("Report the chapter and page"),
		gesture="kb:alt+p",
	)
	def script_reportPage(self, gesture):
		if not self._sayStatus():
			gesture.send()

	# -- contents and bookmarks (Meb shows both as toolbar popups) --

	def _popup(self, wanted):
		for window in _mebWindows():
			header = next(_children(window), None)
			if header and header.CurrentAutomationId == "HeaderTextBlock" and wanted(window, header):
				return window
		return None

	def _openToc(self, then):
		"""Open the contents popup and call then(popup). False if this reader has no contents button."""
		label = _findInMeb(lambda e: e.CurrentAutomationId == "TocButtonLabel")
		if not label:
			return False
		# The contents popup's header repeats the button's label (สารบัญ); the bookmark popup's doesn't.
		name = label.CurrentName
		self._withPopup(
			_client().RawViewWalker.GetParentElement(label),
			lambda window, header: header.CurrentName == name,
			then,
		)
		return True

	def _openBookmarks(self, then):
		"""Open the bookmark popup and call then(popup). False if this reader has no bookmark button."""
		button = _findInMeb(lambda e: e.CurrentAutomationId == "BookmarkButton")
		if not button:
			return False
		self._withPopup(button, self._isBookmarkPopup, then)
		return True

	def _isBookmarkPopup(self, window, header):
		add = _rawChild(window, "BottomButton")  # "Add Bookmark"; hidden in the contents popup
		return bool(add) and not add.CurrentIsOffscreen

	def _withPopup(self, button, wanted, then, retried=False):
		"""Open one of Meb's toolbar popups (unless it's open already) and call then(popup).
		Meb's buttons toggle their popup and can get out of step, so a second press is tried once."""
		popup = self._popup(wanted)
		if popup:
			then(popup)
			return
		_invoke(button)

		def retry():
			if retried:
				# Translators: Reported when Meb doesn't open its contents or bookmark list.
				ui.message(_("Meb did not open the list"))
			else:
				self._withPopup(button, wanted, then, retried=True)

		_waitFor(lambda: self._popup(wanted), then, retry, tries=15)

	def _closePopup(self, popup):
		close = _rawChild(popup, "CloseButton")
		if close:
			_invoke(close)

	def _afterJump(self, before, readAll):
		"""Once Meb has moved to another chapter or page, move into the text there."""
		frame = self._frame()
		if frame:
			_waitFor(
				lambda: self._status(frame) != before,
				lambda found: self._focusText("page", readAll),
				lambda: self._focusText("page", readAll),
				tries=30,
			)

	@script(
		# Translators: Describes the command that shows the book's chapter list.
		description=_("Show the chapter list"),
		gesture="kb:alt+c",
	)
	def script_chapterList(self, gesture):
		if not self._openToc(self._showChapters):
			gesture.send()

	def _showChapters(self, popup):
		names = [_itemText(item) for item in _listItems(popup)]
		self._closePopup(popup)
		frame = self._frame()
		st = frame and self._status(frame)
		current = next((i for i, n in enumerate(names) if st and n == st[0]), 0)
		_ListDialog(
			# Translators: Title of the chapter list dialog.
			_("Chapters"),
			# Translators: Label of the list in the chapter list dialog.
			_("&Chapters:"),
			names,
			current,
			self._goToChapter,
		).show()

	def _goToChapter(self, index):
		def select(popup):
			items = _listItems(popup)
			if index < len(items):
				before = self._status(self._frame())
				_select(items[index])
				self._afterJump(before, config.conf["virtualBuffers"]["autoSayAllOnPageLoad"])

		_whenMebActive(lambda: self._openToc(select))

	@script(
		# Translators: Describes the command that bookmarks the current page.
		description=_("Add a bookmark at the current page"),
		gesture="kb:alt+b",
	)
	def script_addBookmark(self, gesture):
		def add(popup):
			_invoke(_rawChild(popup, "BottomButton"))
			frame = self._frame()
			st = frame and self._status(frame)
			# Translators: Reported after adding a bookmark.
			msg = _("Bookmark added")
			ui.message(f"{msg}, {st[0]}, {st[1]}" if st and st[0] else msg)

		if not self._openBookmarks(add):
			gesture.send()

	@script(
		# Translators: Describes the command that lists the book's bookmarks.
		description=_("Show bookmarks"),
		gesture="kb:alt+shift+b",
	)
	def script_bookmarkList(self, gesture):
		if not self._openBookmarks(self._showBookmarks):
			gesture.send()

	def _showBookmarks(self, popup):
		names = [_itemText(item) for item in _listItems(popup)]
		self._closePopup(popup)
		if not names:
			# Translators: Reported when the book has no bookmarks.
			ui.message(_("No bookmarks"))
			return
		_ListDialog(
			# Translators: Title of the bookmark list dialog.
			_("Bookmarks"),
			# Translators: Label of the list in the bookmark list dialog.
			_("&Bookmarks:"),
			names,
			0,
			self._goToBookmark,
			self._deleteBookmark,
		).show()

	def _goToBookmark(self, index):
		def select(popup):
			items = _listItems(popup)
			if index < len(items):
				before = self._status(self._frame())
				_select(items[index])
				self._afterJump(before, False)

		_whenMebActive(lambda: self._openBookmarks(select))

	def _deleteBookmark(self, index):
		def delete(popup):
			items = _listItems(popup)
			buttons = (
				[
					c
					for c in _children(items[index])
					if c.CurrentControlType == TYPE_BUTTON and not c.CurrentName and not c.CurrentIsOffscreen
				]
				if index < len(items)
				else []
			)
			if len(buttons) >= 2:  # pencil (rename), then bin (delete); Meb deletes without asking
				_invoke(buttons[1])
				# Translators: Reported after deleting a bookmark.
				ui.message(_("Bookmark deleted"))
			self._closePopup(popup)

		_whenMebActive(lambda: self._openBookmarks(delete))

	# -- shelf --

	@script(
		# Translators: Describes the commands that go to a section of Meb's side menu.
		description=_(
			"Go to a shelf section: 1 bookshelf, 2 collections, 3 My Cloud, 4 news feed, 5 notifications",
		),
		gestures=[f"kb:alt+{n}" for n in range(1, 6)],
	)
	def script_shelfSection(self, gesture):
		frame = self._frame()
		nav = frame and _child(frame, "ScrollViewer")
		items = (
			[
				t
				for t in _children(nav)
				if t.CurrentControlType == TYPE_TEXT
				and t.CurrentName.strip()
				and not t.CurrentName.strip().isdigit()
			]
			if nav
			else []
		)
		n = int(gesture.mainKeyName) - 1
		if n >= len(items):
			gesture.send()
			return
		ui.message(items[n].CurrentName)
		_click(items[n])

	@script(
		# Translators: Describes the command that searches the MEB web store.
		description=_("Search the MEB store (opens the results in your web browser)"),
		gesture="kb:alt+s",
	)
	def script_searchStore(self, gesture):
		def ask():
			dlg = wx.TextEntryDialog(
				gui.mainFrame,
				# Translators: Prompt of the store search dialog.
				_("Search the MEB store for:"),
				# Translators: Title of the store search dialog.
				_("Search the MEB store"),
			)
			ok = gui.displayDialogAsModal(dlg) == wx.ID_OK
			term = dlg.GetValue().strip()
			dlg.Destroy()
			if ok and term:
				os.startfile(STORE_SEARCH_URL + urllib.parse.quote(term))

		wx.CallAfter(ask)

	# -- diagnostics --

	@script(
		# Translators: Describes the command that copies information for bug reports.
		description=_("Copy diagnostic information about the focused control, for bug reports"),
		gesture="kb:alt+shift+r",
	)
	def script_copyDiagnostics(self, gesture):
		try:
			version = addonHandler.getCodeAddon().version
		except addonHandler.AddonError:
			version = "scratchpad"
		fg, focus = api.getForegroundObject(), api.getFocusObject()
		frame = self._frame()
		lines = [
			f"MEB Access {version}; NVDA {buildVersion.version}; {winVersion.getWinVer()}; Meb {fg.appModule.productVersion}",
			f"Reader status: {frame and self._status(frame)}",
			f"Focus: role={focus.role.name} name={focus.name!r} app={focus.appModule.appName} window={focus.windowClassName}",
		]
		if isinstance(focus, UIA):
			walker, el = _client().RawViewWalker, focus.UIAElement
			path, node = [], el
			for depth in range(8):
				node = walker.GetParentElement(node)
				if not node:
					break
				path.append(f"{node.CurrentClassName}#{node.CurrentAutomationId}")
			lines.append("Ancestors: " + " < ".join(path))
			parent = walker.GetParentElement(el)
			for sib, (aid, ctype, name, offscreen) in _rawChildren(parent)[:60] if parent else []:
				marker = "->" if _client().CompareElements(sib, el) else "  "
				lines.append(
					f"{marker} {ctype} {sib.CachedClassName} id={aid!r} name={name[:50]!r}{' offscreen' if offscreen else ''}",
				)
		api.copyToClip("\n".join(lines))
		# Translators: Reported after copying diagnostic information.
		ui.message(_("Diagnostic information copied to the clipboard. It may contain book titles."))
