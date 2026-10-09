-- @NAME@: exports the original files of the items selected in Photos into
-- <work>/in (input: the work folder's path), and returns one line per
-- selected item, "id|date|filename", for the shell to match the exported
-- files to the items (a Live Photo is one item, exported as a photo and a
-- .mov). The date is the item's in Photos, "2024-01-01 17:00:00" as the Mac's
-- clock shows it (Photos gives it in the Mac's time zone; the shell adds the
-- offset), empty if Photos gives none.
-- "using originals": the file as it was recorded or imported (an edited
-- item's edits are not applied, nor a date changed in Photos); without it,
-- Photos renders a copy. On an error, returns "ERROR: ...".
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
					set dateText to ""
					try
						set dateText to my wallTime(date of m)
					end try
					set idText to idText & (id of m) & "|" & dateText & "|" & (filename of m) & linefeed
				end repeat
				export sel to dest with using originals
			end tell
		end timeout
		return idText
	on error e number errNum
		return "ERROR: Photos could not export the selected items (" & errNum & ": " & e & ")"
	end try
end run

-- "2024-01-01 17:00:00"
on wallTime(d)
	set t to time of d
	return (year of d as text) & "-" & my two(month of d as integer) & "-" & my two(day of d) & " " & my two(t div hours) & ":" & my two((t mod hours) div minutes) & ":" & my two(t mod minutes)
end wallTime

on two(n)
	return text -2 thru -1 of ("0" & n)
end two
