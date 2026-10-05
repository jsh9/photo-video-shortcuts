-- Compress Photos (macOS): is Photos in front with photos selected?
-- Returns "SELECTION" and the count, or "NONE" (then the shortcut opens its
-- photo picker). No Shortcuts variable may appear in this text: the script
-- would not compile (see build_mac_shortcuts.py).
on run {input, parameters}
	try
		tell application "Photos"
			if frontmost then
				set n to count of selection
				if n > 0 then return "SELECTION " & n
			end if
		end tell
		return "NONE"
	on error e number errNum
		return "NONE (" & errNum & ": " & e & ")"
	end try
end run
