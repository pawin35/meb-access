# Self-check for the MEB Access add-on outside NVDA (Windows): uv run python tests/check_meb.py [--network]
# Stubs NVDA's modules, then tests the pure logic with data captured from Meb 2.0.50's UI tree, checks the
# Thai translation is complete, and runs the OCR path (NVDA-style BGRA buffer -> Tesseract) when an engine
# is available. --network first downloads the pinned OCR engine exactly as the add-on does.
import ast
import builtins
import ctypes
import difflib
import glob
import hashlib
import importlib.util
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from types import SimpleNamespace as NS
from unittest import mock

from PIL import Image, ImageDraw, ImageFont

# Loading the plugin must not leave a __pycache__ in addon/, or local builds would package it.
sys.dont_write_bytecode = True

for name in (
    "api", "appModuleHandler", "buildVersion", "config", "controlTypes", "core", "eventHandler", "logHandler",
    "mouseHandler", "ui", "UIAHandler", "winUser", "winVersion", "speech", "speech.extensions", "NVDAObjects",
):
	sys.modules[name] = mock.MagicMock()
cls = lambda name: type(name, (), {})  # real classes where the add-on subclasses them
sys.modules["textInfos"] = mock.MagicMock(TextInfo=cls("TextInfo"))
sys.modules["NVDAObjects.IAccessible"] = mock.MagicMock(IAccessible=cls("IAccessible"))
sys.modules["virtualBuffers"] = mock.MagicMock(VirtualBuffer=cls("VirtualBuffer"))

class CodepointConverter:  # textUtils' converter for text whose code points are one offset each (all of Thai)
	def __init__(self, text):
		self.text = text

	def strToEncodedOffsets(self, start, end=None):
		return start if end is None else (start, end)

sys.modules["textUtils"] = mock.MagicMock(getOffsetConverter=lambda encoding: CodepointConverter)
sys.modules["addonHandler"] = mock.MagicMock(AddonError=type("AddonError", (Exception,), {}))
sys.modules["globalVars"] = mock.MagicMock(**{"appArgs.secure": False})
sys.modules["globalPluginHandler"] = mock.MagicMock(GlobalPlugin=cls("GlobalPlugin"))
sys.modules["comtypes"] = mock.MagicMock(COMError=type("COMError", (Exception,), {}))
sys.modules["contentRecog"] = mock.MagicMock(ContentRecognizer=cls("ContentRecognizer"))
sys.modules["NVDAObjects.UIA"] = mock.MagicMock(UIA=cls("UIA"))
sys.modules["NVDAObjects.behaviors"] = mock.MagicMock(Dialog=cls("Dialog"))
sys.modules["wx"] = mock.MagicMock(Dialog=cls("Dialog"))
settingsDialogs = mock.MagicMock(SettingsPanel=cls("SettingsPanel"))
sys.modules["gui"] = mock.MagicMock(settingsDialogs=settingsDialogs)
sys.modules["gui.settingsDialogs"] = settingsDialogs
sys.modules["gui.guiHelper"] = mock.MagicMock()
sys.modules["gui.message"] = mock.MagicMock()
sys.modules["scriptHandler"] = mock.MagicMock(script=lambda **kw: (lambda f: f))
builtins._ = lambda s: s  # NVDA installs _ globally; initTranslation is stubbed

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("mebAccess", os.path.join(root, "addon", "globalPlugins", "mebAccess.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
B, T, I = m.TYPE_BUTTON, m.TYPE_TEXT, 50006

# Shelf list children, as dumped from the real app (aid, controlType, name, offscreen).
def book(title, *, sample=False, notDownloaded=False, downloading=False, waiting=False, progress="0%"):
	return [
     ("", T, title, True), ("", I, "", False), ("", I, "", False), ("BrushOne", I, "", False),
     ("", T, "Sample", not sample), ("", T, "Update", True), ("", I, "", True), ("", T, "", True),
     ("", T, "Waiting...", not waiting), ("StopDownloadBtn", B, "", not downloading),
     ("DownloadBookBtn", B, "", not notDownloaded), ("", I, "", True), ("IssueLabel", T, "4", True),
     ("", T, progress, False), ("", T, "จบ", True), ("", B, "", False),
 ]
scroll = [("VerticalScrollBar", 50014, "", True), ("HorizontalScrollBar", 50014, "", True)]
shelf = book("ฉันเป็นศิษย์จอมปราชญ์จริงๆ นะ 4", sample=True) + book("การสูญพันธุ์ครั้งที่ 6", progress="3%") + scroll
books = m.parseShelf(shelf)
assert [b["title"] for b in books] == ["ฉันเป็นศิษย์จอมปราชญ์จริงๆ นะ 4", "การสูญพันธุ์ครั้งที่ 6"]
assert (books[0]["cover"], books[0]["anchor"], books[1]["cover"], books[1]["anchor"]) == (3, 15, 19, 31)
assert m.bookName(books[0]) == "ฉันเป็นศิษย์จอมปราชญ์จริงๆ นะ 4, Sample, 0%"
assert m.bookName(books[1]) == "การสูญพันธุ์ครั้งที่ 6, 3%"
assert m.bookName(m.parseShelf(book("X", notDownloaded=True))[0]) == "X, not downloaded, 0%"   # first session
assert m.parseShelf(book("X", downloading=True))[0]["state"] == "downloading"
assert m.parseShelf(book("X", waiting=True))[0]["state"] == "waiting"
assert m.parseShelf(scroll) == []
assert m.headerCount("หนังสือทั้งหมด (2)") == 2 and m.headerCount("ผลการค้นหา (0)") == 0 and m.headerCount("x") is None

# Shelf announcements between snapshots.
snap = lambda header="หนังสือทั้งหมด (2)", syncing=False, banner=False, **books: {
	"header": header, "syncing": syncing, "syncText": "กำลังซิงก์หนังสือกับเซิฟเวอร์...",
	"banner": banner, "bannerText": "", "books": books,
}
assert m.shelfChanges(snap(A=""), snap(A="")) == []
assert m.shelfChanges(snap(A=""), snap(header="ผลการค้นหา (0)")) == ["ผลการค้นหา (0)"]
assert m.shelfChanges(snap(), snap(syncing=True)) == ["กำลังซิงก์หนังสือกับเซิฟเวอร์..."]
assert m.shelfChanges(snap(syncing=True), snap()) == ["Sync finished"]
assert m.shelfChanges(snap(), snap(banner=True)) == ["Meb found books you may have finished"]
assert m.shelfChanges(snap(A="waiting"), snap(A="downloading")) == ["Downloading A"]
assert m.shelfChanges(snap(A="downloading"), snap(A="")) == ["A downloaded"]
assert m.shelfChanges(snap(A="notDownloaded"), snap(A="")) == []    # e.g. list re-rendered

# Labels.
L = m.labelFor
assert L("ThemeButton", "ปกติ", "ThemeButtonLabel", [], "", False) == "Theme: ปกติ"
assert L("", "หน้าเดี่ยว", "DoublePageModeLabel", [], "", False) == "Page layout: หน้าเดี่ยว"
assert L("SortByButton", "กิจกรรมล่าสุด", "", [], "", False) == "Sort by: กิจกรรมล่าสุด"
assert L("", "อ่านจบแล้ว", "", [], "", False) == "อ่านจบแล้ว"            # book menu item
assert L("SettingButton", "", "", [], "", False) == "Settings"
assert L("TextBoxSearch", "", "", [], "", False) == "Search my books"
assert L("CloseButton", "X", "", [], "", False) == "Close"               # popups' bare "X"
assert L("", "", "", [], "", False, listItemButton=0) == "Rename bookmark"
assert L("", "", "", [], "", False, listItemButton=1) == "Delete bookmark"
assert L("", "", "", [], "BookTitle", False) == "Back"                   # reader back button
assert L("", "", "", [], "TocButton", True) == "Back"                    # toolbar back button (top-left)
assert L("", "", "", [], "ZoomSlider", False) == "Zoom out"
assert L("", "", "", ["ZoomSlider"], "", False) == "Zoom in"
assert L("", "", "", [], "", False) == ""

# Reader status line.
image = [(B, ""), (T, "การสูญพันธุ์ครั้งที่ 6"), (T, " หน้า 4 จาก 121")]
epub = [(B, ""), (T, "Cover"), (T, " - "), (T, "หน้า 1 จาก 1")]
assert m.readerStatus(image) == ("", "หน้า 4 จาก 121", 4, 121)
assert m.readerStatus(epub) == ("Cover", "หน้า 1 จาก 1", 1, 1)
assert m.readerStatus([(I, ""), (T, "FB-5711996682178165"), (B, "")]) is None
st = lambda ch, p, n: (ch, f"หน้า {p} จาก {n}", p, n)
start = st("Ch1", 3, 25)
assert not m.isNewChapter(start, st("Ch1", 24, 25), st("Ch1", 25, 25))
assert m.isNewChapter(start, st("Ch1", 25, 25), st("Ch2", 1, 30))
assert m.isNewChapter(start, st("Ch1", 25, 25), st("Ch1", 1, 25))       # same title, page reset
assert not m.isNewChapter(start, st("Ch1", 2, 25), st("Ch1", 1, 25), forward=False)
assert m.isNewChapter(start, st("Ch1", 1, 25), st("Ch0", 18, 18), forward=False)
assert m.isNewChapter(start, st("Ch1", 1, 25), st("Ch1", 25, 25), forward=False)  # same title, page jumped up

# Resume point: measured on page 3 of the sample (WebView at x 57..1863). A text node wholly on the page
# is hit at its start; a paragraph continued from page 2 starts left of the view, so aim at its first
# visible line's right end.
host = (57, 97, 1863, 1061)
assert m.textPoint((417, 102, 1503, 400), host) == (420, 105)
assert m.textPoint((-1500, 102, 1503, 960), host) == (1493, 105)

# The Meb gate runs for every object and key press system-wide, so it must never raise.
assert m._isMeb(NS(appModule=NS(appName="meb")))
assert not m._isMeb(None) and not m._isMeb(NS(appModule=None)) and not m._isMeb(object())
# On secure screens (logon, UAC) the plugin is swapped for NVDA's do-nothing base class.
base = sys.modules["globalPluginHandler"].GlobalPlugin
assert m.GlobalPlugin is not base
m.globalVars.appArgs.secure = True
assert m._disabledInSecureMode(m.GlobalPlugin) is base
m.globalVars.appArgs.secure = False

# Zero-width spaces (3,833 in one chapter of the sample) are filtered out of speech...
Z = chr(0x200B)
assert m.stripZwsp([f"เหนือ{Z}ท้องฟ้า", 42, f"{Z}ทิศ"]) == ["เหนือท้องฟ้า", 42, "ทิศ"]

# ...and hidden in the reading pane's browse mode text. FakeVBufText stands in for NVDA's virtual buffer
# TextInfo over a real line from a Meb book: one offset per code point, words split at zero-width spaces
# (as NVDA's word segmenter does), each zero-width space its own "word".
line = f"ที่{Z}ซีเลมี{Z}ร้าน{Z}มังกร{Z}สอง{Z}ร้าน"
zwsps = [i for i, c in enumerate(line) if c == Z]

class FakeVBufText(sys.modules["textInfos"].TextInfo):
	encoding = "utf_32_le"

	def __init__(self, start=0, end=len(line)):
		self._startOffset, self._endOffset = start, end

	def copy(self):
		return type(self)(self._startOffset, self._endOffset)

	def _getTextRange(self, start, end):
		return line[start:end]

	def _getStoryLength(self):
		return len(line)

	def _getCharacterOffsets(self, offset):
		return offset, offset + 1

	def _getWordOffsets(self, offset):
		if line[offset] == Z:
			return offset, offset + 1
		start = max([z + 1 for z in zwsps if z < offset] + [0])
		return start, min([z for z in zwsps if z > offset] + [len(line)])

	def _get_text(self):
		return line[self._startOffset:self._endOffset]

	def getTextWithFields(self, formatConfig=None):
		return ["field", self._get_text()] if self._startOffset < self._endOffset else ""

	def moveToCodepointOffset(self, codepointOffset):
		result = self.copy()
		result._startOffset = result._endOffset = self._startOffset + codepointOffset
		return result

class HiddenText(m.ZwspHidingTextInfo, FakeVBufText):
	pass

hidden = HiddenText()
assert hidden._get_text() == line.replace(Z, "") and hidden.getTextWithFields() == ["field", line.replace(Z, "")]
assert HiddenText(3, 3).getTextWithFields() == ""
# A zero-width space belongs to the character (and word) before it, so moving never lands on one.
first = zwsps[0]
assert hidden._getCharacterOffsets(first - 1) == (first - 1, first + 1)
assert hidden._getCharacterOffsets(first) == (first - 1, first + 1)
assert hidden._getWordOffsets(0) == (0, first + 1) and hidden._getWordOffsets(first) == (0, first + 1)
stops, pos = [], 0
while pos < len(line):
	stops.append(pos)
	pos = hidden._getCharacterOffsets(pos)[1]
assert not set(stops) & set(zwsps) and len(stops) == len(line.replace(Z, ""))
back, pos = [], len(line)
while pos > 0:
	pos = hidden._getCharacterOffsets(pos - 1)[0]
	back.append(pos)
assert sorted(back) == stops
# Braille routing: the 4th hidden character (ซ, after "ที่") is at raw offset 4, past the zero-width space.
assert m.rawIndex(line, 3) == 4 and m.rawIndex(line, len(line.replace(Z, ""))) == len(line)
assert hidden.moveToCodepointOffset(3)._startOffset == 4
assert HiddenText(4).moveToCodepointOffset(6)._startOffset == line.index("ร้าน")
# With the setting off, the text is left exactly as the book has it.
realConf, m._conf = m._conf, lambda key: False
assert hidden._get_text() == line and hidden._getCharacterOffsets(first) == (first, first + 1)
assert hidden.moveToCodepointOffset(4)._startOffset == 4
m._conf = realConf
# The reading pane swaps in the hiding text class only for virtual buffers.
VBuf = sys.modules["virtualBuffers"].VirtualBuffer
ChromeVBuf = type("ChromeVBuf", (VBuf,), {"TextInfo": FakeVBufText})
swapped = m._zwspHidingBuffer(ChromeVBuf)
assert issubclass(swapped, ChromeVBuf) and issubclass(swapped.TextInfo, m.ZwspHidingTextInfo)
assert issubclass(swapped.TextInfo, FakeVBufText) and m._zwspHidingBuffer(ChromeVBuf) is swapped

# Visible page among FlipView's previous/current/next images.
assert m.pickPage([(-1900, 52, -100, 1100), (300, 52, 1600, 1100), (2000, 52, 3800, 1100)], (0, 0, 1920, 1130)) == 1
assert m.pickPage([(-1900, 52, -100, 1100)], (0, 0, 1920, 1130)) is None

# OCR cache keeps the most recently used pages.
cache = m.OcrCache(limit=2)
cache.put("p1", "a"); cache.put("p2", "b"); cache.get("p1"); cache.put("p1", "a"); cache.put("p3", "c")
assert list(cache) == ["p1", "p3"]

# NVDA hands recognizers a 2-D array of RGBQUAD (b, g, r, reserved).
class RGBQUAD(ctypes.Structure):
	_fields_ = [("b", ctypes.c_ubyte), ("g", ctypes.c_ubyte), ("r", ctypes.c_ubyte), ("x", ctypes.c_ubyte)]
px = ((RGBQUAD * 3) * 2)()
px[1][2].r = 255
img = m.pixelsToImage(px, 3, 2)
assert img.size == (3, 2) and img.getpixel((2, 1)) == 76 and img.getpixel((0, 0)) == 0
assert m.cleanOcrText(" ก" + chr(0x0E4D) + chr(0x0E32) + "ลัง \n") == "กำลัง"

# Translations: every string passed to _() in the add-on and buildVars.py (store summary, description,
# changelog) is translated in each .po file, with {placeholders} intact. The .po must compile and load.
def sourceMsgids():
	paths = glob.glob(os.path.join(root, "addon", "**", "*.py"), recursive=True) + [os.path.join(root, "buildVars.py")]
	ids = set()
	for path in paths:
		with open(path, encoding="utf-8") as f:
			tree = ast.parse(f.read())
		for node in ast.walk(tree):
			if (
       isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_" and node.args
       and isinstance(node.args[0], ast.Constant)
   ):
				ids.add(node.args[0].value)
	return ids

def parsePo(path):
	"""{msgid: msgstr}; handles multi-line strings (the add-on uses no plurals or contexts)."""
	entries, cur, key = {}, {}, None
	with open(path, encoding="utf-8") as f:
		lines = f.read().splitlines()
	for line in [ln.strip() for ln in lines] + ["msgid END"]:
		match = re.match(r"(msgid|msgstr) (.*)$", line)
		if match and match.group(1) == "msgid" and "msgstr" in cur:
			entries[cur["msgid"]] = cur["msgstr"]
			cur = {}
		if match:
			key = match.group(1)
			cur[key] = "" if match.group(2) == "END" else ast.literal_eval(match.group(2))
		elif line.startswith('"') and key:
			cur[key] += ast.literal_eval(line)
	return entries

wanted = sourceMsgids()
for po in glob.glob(os.path.join(root, "addon", "locale", "*", "LC_MESSAGES", "nvda.po")):
	lang = po.split(os.sep)[-3]
	entries = {k: v for k, v in parsePo(po).items() if v}
	missing = sorted(wanted - entries.keys())
	assert not missing, f"{lang}: untranslated strings: {missing}"
	placeholders = lambda s: sorted(re.findall(r"\{\w+\}", s))
	broken = [k for k, v in entries.items() if placeholders(k) != placeholders(v)]
	assert not broken, f"{lang}: translations that change placeholders: {broken}"
	stale = sorted(k for k in entries.keys() - wanted if k)
	assert not stale, f"{lang}: entries no longer used by the code: {stale}"
	print(f"{lang} translation: {len(entries) - 1} strings, complete")

# OCR engine download: unpacks only the engine and English data, adds Thai, enforces checksums,
# refuses paths outside the target, and leaves a working engine alone when an attempt fails.
def fakeBundle(*extra):
	buf = io.BytesIO()
	with zipfile.ZipFile(buf, "w") as z:
		for name, data in [
      ("manifest.ini", b"m"), ("libs/tesseract64/tesseract.exe", b"exe"),
      ("libs/tesseract64/libtesseract-5.dll", b"dll"), ("libs/tesseract64/tessdata/eng.traineddata", b"eng"),
      ("libs/tesseract64/tessdata/osd.traineddata", b"osd"), ("libs/xpdf-tools64/pdftopng.exe", b"pdf"), *extra,
  ]:
			z.writestr(name, data)
	return buf.getvalue()

pinned = (dict(m.ENGINE_BUNDLE), dict(m.EXTRA_TESSDATA))
def fakeServer(bundle, tha=b"tha"):
	m.ENGINE_BUNDLE.update(url="bundle", sha256=hashlib.sha256(bundle).hexdigest())
	m.EXTRA_TESSDATA = {"tha": ("tha", hashlib.sha256(tha).hexdigest())}
	return lambda url, progress: {"bundle": bundle, "tha": tha}[url]

def mustFail(action):
	try:
		action()
	except ValueError:
		return
	raise AssertionError("expected ValueError")

work = tempfile.mkdtemp()
target = os.path.join(work, "tesseract")
m.installEngine(target, fakeServer(fakeBundle()))
files = sorted(os.path.relpath(os.path.join(r, f), target).replace("\\", "/") for r, ds, fs in os.walk(target) for f in fs)
assert files == ["libtesseract-5.dll", "tessdata/eng.traineddata", "tessdata/tha.traineddata", "tesseract.exe"], files
download = fakeServer(fakeBundle())
m.ENGINE_BUNDLE["sha256"] = "0" * 64
mustFail(lambda: m.installEngine(target, download))
mustFail(lambda: m.installEngine(target, fakeServer(fakeBundle(("libs/tesseract64/../../evil.txt", b"x")))))
download = fakeServer(fakeBundle())
m.EXTRA_TESSDATA = {"tha": ("tha", "0" * 64)}  # Thai data that doesn't match its pinned checksum
mustFail(lambda: m.installEngine(target, download))
assert os.path.isfile(os.path.join(target, "tesseract.exe")) and not os.path.exists(target + ".partial")
assert not os.path.exists(os.path.join(work, "evil.txt"))
m.ENGINE_BUNDLE.clear(); m.ENGINE_BUNDLE.update(pinned[0]); m.EXTRA_TESSDATA = pinned[1]
shutil.rmtree(work)

# End-to-end OCR through the same command the plugin runs. With --network, first download the pinned
# engine exactly as the add-on does (run this after bumping ENGINE_BUNDLE or EXTRA_TESSDATA).
exe = os.path.join(os.environ.get("APPDATA", ""), r"nvda\addons\tesseractOCR\globalPlugins\tesseractOCR\tesseract\tesseract.exe")
netDir = None
if "--network" in sys.argv:
	netDir = tempfile.mkdtemp()
	steps = []
	m.installEngine(os.path.join(netDir, "tesseract"), m._download, steps.append)
	exe = os.path.join(netDir, "tesseract", "tesseract.exe")
	print("downloaded the pinned OCR engine; progress reported at", steps)
	assert steps == [25, 50, 75], steps
if os.path.isfile(exe):
	lines = [
     "เหนือท้องฟ้าทิศตะวันตกของราชอาณาจักรอัลไคต์ เพกาซัสตัวหนึ่งกำลังบินข้ามเทือกเขา",
     "สิ่งที่แผ่ตัวอยู่เบื้องล่างคือพงไพรสีเขียวที่ทอดยาวสุดลูกหูลูกตา",
     "ในตอนนั้นเอง จู่ๆ ก็เกิดแรงสั่นเบาๆ ขึ้นที่เท้า มีเสียงเหมือนอะไรแข็งๆ แตกดังลั่น",
     "“จะมองสักกี่ทีก็ยังกว้างใหญ่เหมือนเดิม”",
 ]  # 4+ lines: a body-text page (1-2 line pages score lower)
	# Meb's own body font when Meb is installed; Tahoma (on every Windows, e.g. CI) scores the same.
	fonts = [r"C:\Program Files\Meb\Resource\Font\Garuda.ttf", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "tahoma.ttf")]
	font = ImageFont.truetype(next(f for f in fonts if os.path.isfile(f)), 17)
	page = Image.new("RGB", (820, 230), "white")
	for i, line in enumerate(lines):
		ImageDraw.Draw(page).text((45, 45 + i * 34), line, fill="black", font=font)
	raw = page.convert("RGBA").tobytes("raw", "BGRA")
	buf = ((RGBQUAD * page.width) * page.height).from_buffer_copy(raw)
	png = io.BytesIO()
	m.pixelsToImage(buf, page.width, page.height).save(png, "PNG")  # same as TesseractRecognizer._run
	langs = ("tha", "eng")
	assert m.missingOcrLangs(exe, langs) == [] and m.missingOcrLangs(exe, ("xyz",)) == ["xyz"]
	out = subprocess.run(m.tesseractCommand(exe, langs), input=png.getvalue(), capture_output=True, timeout=120)
	assert out.returncode == 0, out.stderr
	got = m.cleanOcrText(out.stdout.decode("utf-8", "replace"))
	score = difflib.SequenceMatcher(
     None, "".join(lines).replace(" ", ""), got.replace(" ", "").replace("\n", ""),
     autojunk=False,
 ).ratio()
	print(f"OCR similarity {score:.0%}: {got[:60]}...")
	assert score > 0.9, got
else:
	print("no Tesseract found: OCR check skipped (run with --network to download the add-on's own engine)")
if netDir:
	shutil.rmtree(netDir)
print("all checks passed")
