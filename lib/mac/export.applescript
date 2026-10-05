-- Compress Photos (macOS): exports the original files of the photos selected
-- in Photos into <work>/in (input: the work folder's path), and returns one
-- line per selected photo, "id|filename", for the shell to match the exported
-- files to the photos. "using originals": the original file as it was
-- imported (an edited photo's edits are not applied); without it, Photos
-- renders JPEGs. On an error, returns "ERROR: ...".
on run {input, parameters}
	try
		set work to item 1 of input as text
		set dest to POSIX file (work & "/in/")
		-- Exporting many photos, or ones iCloud must first download, takes
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
		return "ERROR: Photos could not export the selected photos (" & errNum & ": " & e & ")"
	end try
end run
