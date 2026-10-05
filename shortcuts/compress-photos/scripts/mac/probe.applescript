-- Compress Photos (macOS): is Photos in front with photos selected?
-- Returns "SELECTION" and the count, "NONE" (then the shortcut opens its photo
-- picker), or "ERROR: ..." (for example, Shortcuts may not control Photos; the
-- shortcut shows it, then opens the picker). Photos is only asked when it is
-- running: a tell block would launch it otherwise. No Shortcuts variable may
-- appear in this text: the script would not compile (see
-- build_mac_shortcuts.py).
on run {input, parameters}
	try
		if application "Photos" is running then
			tell application "Photos"
				if frontmost then
					set n to count of selection
					if n > 0 then return "SELECTION " & n
				end if
			end tell
		end if
		return "NONE"
	on error e number errNum
		return "ERROR: Photos could not be asked for its selection (" & errNum & ": " & e & "). If macOS asked whether Shortcuts may control Photos, allow it in System Settings > Privacy & Security > Automation."
	end try
end run
