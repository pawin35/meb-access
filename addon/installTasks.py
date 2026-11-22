# MEB Access install tasks. Copyright (C) 2026 MEB Access contributors. GNU GPL v2; see LICENSE.
import os
import shutil

import addonHandler
import globalVars


def onUninstall():
	# NVDA also runs this when replacing the old version during an update; the new version is then
	# waiting in a ".pendingInstall" folder. Keep the downloaded OCR engine for it in that case.
	addonsDir = os.path.join(globalVars.appArgs.configPath, "addons")
	if os.path.isdir(os.path.join(addonsDir, "mebAccess" + addonHandler.ADDON_PENDINGINSTALL_SUFFIX)):
		return
	shutil.rmtree(os.path.join(globalVars.appArgs.configPath, "mebAccess"), ignore_errors=True)
