-- @NAME@: exports the original files of the items selected in Photos into
-- <work>/in (input: the work folder's path), and returns one line per
-- selected item, "id|filename", for the shell to match the exported files to
-- the items (a Live Photo is one item, exported as a photo and a .mov).
-- "using originals": the file as it was recorded or imported (an edited
-- item's edits are not applied); without it, Photos renders a copy. On an
-- error, returns "ERROR: ...".
on run {input, parameters}
	try
		set work to item 1 of input as text
		set dest to POSIX file (work & "/in/")
		-- Exporting many items, or ones iCloud must first download, takes
		-- longer than AppleScript's default 2-minute limit on one command.
		with timeout of 3600 seconds
			tell application "Photos"
				set sel to selection
				if (count of sel) is 0 then return "ERROR: nothing is selected in Photos."
				set idText to ""
				repeat with i from 1 to count of sel
					set m to item i of sel
					set idText to idText & (id of m) & "|" & (filename of m) & linefeed
				end repeat
				export sel to dest with using originals
			end tell
		end timeout
		return idText
	on error e number errNum
		return "ERROR: Photos could not export the selected items (" & errNum & ": " & e & ")"
	end try
end run
