-- @NAME@ (the Mac's route from Photos): exports the current version of each
-- item selected in Photos (its edits applied, as Photos shows it) into
-- <work>/in/<n>, one folder per item in the selection's order (input: the
-- work folder's path), and returns one line per item, "n|date". The date is
-- the item's in Photos, "2024-01-01 17:00:00" as the Mac's clock shows it
-- (Photos gives it in the Mac's time zone; stage.zsh adds the offset), empty
-- if Photos gives none. On an error, returns "ERROR: ...". No Shortcuts
-- variable may appear in this text: the script would not compile.
on run {input, parameters}
	try
		set work to item 1 of input as text
		-- Exporting many items, or ones iCloud must first download, takes
		-- longer than AppleScript's default 2-minute limit on one command.
		with timeout of 3600 seconds
			tell application "Photos"
				set sel to selection
				if (count of sel) is 0 then return "ERROR: nothing is selected in Photos."
				set out to ""
				repeat with i from 1 to count of sel
					set dateText to ""
					try
						set dateText to my wallTime(date of (item i of sel))
					end try
					set dest to work & "/in/" & i
					my makeFolder(dest)
					-- without "using originals": Photos renders the item as it
					-- shows it, a JPEG for a photo
					export {item i of sel} to my folderRef(dest)
					set out to out & i & "|" & dateText & linefeed
				end repeat
			end tell
		end timeout
		return out
	on error e number errNum
		return "ERROR: Photos could not export the selected items (" & errNum & ": " & e & ")"
	end try
end run

-- Photos' sandbox reaches ~/Pictures, where the folder is; the shell makes
-- it (outside the tell block, so Photos isn't asked to).
on makeFolder(p)
	do shell script "mkdir -p " & quoted form of p
end makeFolder

on folderRef(p)
	return POSIX file (p & "/")
end folderRef

-- "2024-01-01 17:00:00", as lib/mac/export.applescript writes it
on wallTime(d)
	set t to time of d
	return (year of d as text) & "-" & my two(month of d as integer) & "-" & my two(day of d) & " " & my two(t div hours) & ":" & my two((t mod hours) div minutes) & ":" & my two(t mod minutes)
end wallTime

on two(n)
	return text -2 thru -1 of ("0" & n)
end two
